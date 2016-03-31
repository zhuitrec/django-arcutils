"""Utilities for setting up a project's settings.

The default way to use this is to import and call :func:`init_settings`
in a project's settings module:

    # project/top_level_package/settings.py
    from arcutils.settings import init_settings
    init_settings()

This adds a few default settings for bootstrapping purposes and then
loads the project's local settings--the django-local-settings variety.

Pass ``local_settings=False`` to :func:`init_settings` if the project
doesn't use django-local-settings.

"""
import base64
import inspect
import ipaddress
import os
import pkg_resources
from datetime import datetime

from django.utils import timezone

from local_settings import NO_DEFAULT, load_and_check_settings, LocalSetting, SecretSetting


ARCUTILS_PACKAGE_DIR = pkg_resources.resource_filename('arcutils', '')


# Considers any standard private IP address a valid internal IP address
def _is_internal_ip_address(self, addr):
    addr = ipaddress.ip_address(addr)
    return addr.is_loopback or addr.is_private
INTERNAL_IPS = type('INTERNAL_IPS', (), dict(__contains__=_is_internal_ip_address))()


def init_settings(settings=None, local_settings=True, prompt=None, quiet=None, level=2):
    """Initialize settings.

    Call this from the global scope of your project's settings module::

        from arcutils.settings import init_settings
        init_settings()

    This assumes the project is structured like so, with the settings
    module in the top level package::

        project directory/
            {top level package}/
                __init__.py
                settings.py
            README.md
            setup.py

    It will add a few default settings that are commonly used in local
    settings files:

        - ARCUTILS_PACKAGE_DIR
        - PACKAGE (top level project package)
        - PACKAGE_DIR (top level project package directory)
        - ROOT_DIR (project directory; should only be used in dev)

    Also adds ``START_TIME`` as the current date/time. This will be
    an "aware" UTC datetime object if the project has time zone support
    enabled (i.e. ``USE_TZ = True``) or a non-aware datetime object if
    not.

    The ``PACKAGE`` and ``PACKAGE_DIR`` settings will be computed
    dynamically (based on the location of the settings module this
    function is called from). If this isn't working, you can set the
    ``PACKAGE`` setting explicitly in the project's settings (before
    calling this function)::

        PACKAGE = 'quickticket'
        init_settings()

    Generally, you won't need to pass ``settings``, but if you do, it
    should be a dict of settings as you'd get from calling ``globals()``
    in the project's settings module.

    .. note:: If your project has additional local settings, they must
        be defined *before* this function is called.

    """
    settings = settings if settings is not None else get_module_globals(level)
    settings.setdefault('ARCUTILS_PACKAGE_DIR', ARCUTILS_PACKAGE_DIR)
    if not settings.get('PACKAGE'):
        settings['PACKAGE'] = derive_top_level_package_name(level)
    settings.setdefault('PACKAGE_DIR', pkg_resources.resource_filename(settings['PACKAGE'], ''))
    settings.setdefault('ROOT_DIR', os.path.dirname(settings['PACKAGE_DIR']))
    if local_settings:
        init_local_settings(settings, prompt=prompt, quiet=quiet)

    # NOTE: We can't simply use Django's timezone.now() here because it
    #       accesses settings.USE_TZ, but at this point the settings
    #       may not be considered fully configured by Django, so we have
    #       to do this to avoid an ImproperlyConfigured exception.
    use_tz = settings.get('USE_TZ', False)
    now = datetime.utcnow().replace(tzinfo=timezone.utc) if use_tz else datetime.now()
    settings.setdefault('START_TIME', now)


def init_local_settings(settings, prompt=None, quiet=None):
    """Initialize the local settings defined in ``settings``.

    Args:
        settings (dict): A dict of settings as you'd get from calling
            ``globals()`` in a Django settings module.
        quiet (bool): Squelch standard out when loading local settings.

    .. note:: If your project has additional local settings, they must
        be defined *before* this function is called.

    """
    suggested_secret_key = base64.b64encode(os.urandom(64)).decode('utf-8')
    defaults = {
        'DEBUG': LocalSetting(False),
        'ADMINS': LocalSetting([]),
        'ALLOWED_HOSTS': LocalSetting([]),
        'GOOGLE': {
            'analytics': {
                'tracking_id': LocalSetting(
                    None, doc='Enter Google Analytics tracking ID (UA-NNNNNNNN-N)'
                ),
            },
        },
        'MANAGERS': LocalSetting([]),
        'SECRET_KEY': SecretSetting(doc='Suggested: "{suggested_secret_key}"'.format_map(locals())),
        'DATABASES': {
            'default': {
                'ENGINE': LocalSetting('django.db.backends.postgresql'),
                'NAME': LocalSetting(settings.get('PACKAGE', NO_DEFAULT)),
                'USER': LocalSetting(''),
                'PASSWORD': SecretSetting(),
                'HOST': LocalSetting(''),
            },
        },
    }
    for k, v in defaults.items():
        settings.setdefault(k, v)
    settings.update(load_and_check_settings(settings, prompt=prompt, quiet=quiet))


NOT_SET = object()


class SettingNotFoundError(LookupError):

    pass


def get_setting(key, default=NOT_SET, settings=None):
    """Get setting for ``key``, falling back to ``default`` if passed.

    ``key`` should be a string like 'ARC.cdn.hosts' or 'X.Y.0'. The key
    is split on dots into path segments, then the settings are traversed
    like this:

        - Set current value to django.conf.settings.{first segment}
        - For each other segment
            - Get current_value[segment] if current value is a dict
            - Get current_value[int(segment)] if current value is a list

    Only dicts, list, and tuples will be traversed. If a segment
    contains some other type of value, a ``ValueError`` will be raised.
    Note that we don't return the default in this case because this
    means an existing setting is being accessed incorrectly.

    If a non-int index is given for a list or tuple segment, this will
    also raise a ``ValueError``.

    If the setting isn't found, the ``default`` value will be returned
    if specified; otherwise, a ``SettingsNotFoundError`` will be raised.

    ``settings`` can be used to retrieve the setting from a settings
     object other than the default ``django.conf.settings``.

    """
    import django.conf

    if settings is None:
        settings = django.conf.settings

    root, *path = key.split('.')
    setting = getattr(settings, root, NOT_SET)

    for segment in path:
        if setting is NOT_SET:
            break
        if isinstance(setting, dict):
            setting = setting.get(segment, NOT_SET)
        elif isinstance(setting, (list, tuple)):
            index = int(segment)
            try:
                setting = setting[index]
            except IndexError:
                setting = NOT_SET
        else:
            raise ValueError('Cannot traverse into setting of type %s' % type(setting))

    if setting is NOT_SET:
        if default is NOT_SET:
            raise SettingNotFoundError('Could not find setting for key "%s"' % key)
        else:
            setting = default

    return setting


def make_prefixed_get_setting(prefix, defaults=None):
    """Make a function that gets settings for a given ``prefix``.

    Args:
        prefix: An upper case setting name such as "CAS" or "LDAP"
        defaults: A dict of defaults for the prefix

    The idea is to make it easy to fetch sub-settings within a given
    package.

    For example::

        >>> DEFAULT_CAS_SETTINGS = {
        ...     'base_url': 'https://example.com/cas/',
        ...     # plus a bunch more CAS settings...
        ... }
        >>> get_cas_setting = make_prefixed_get_setting('CAS', DEFAULT_CAS_SETTINGS)
        >>> base_url = get_cas_setting('base_url')
        >>> login_path = get_cas_setting('logout_path', default='/default/logout/path')

    See the ``cas``, ``ldap``, and ``masquerade`` packages for concrete
    examples of how this is used.

    """

    defaults = PrefixedSettings(prefix, defaults if defaults is not None else {})

    def prefixed_get_setting(key, default=NOT_SET):
        """Get setting for ``prefix``.

        Args:
            key: setting name without ``prefix``
            default: value to use if setting isn't present in the
                project's settings or in the ``defaults``

        Returns:
            object: Value of setting

                Attempt to get setting from:

                1. Project settings for ``prefix``
                2. Default settings from ``defaults``
                3. ``default`` arg

        Raises:
            SettingNotFoundError: When the setting isn't found in the
                project's settings or in the ``defaults`` and no
                fallback is passed via the ``default`` keyword arg

        """
        qualified_key = '{prefix}.{key}'.format(prefix=prefix, key=key)

        try:
            return get_setting(qualified_key)
        except SettingNotFoundError:
            return get_setting(qualified_key, default=default, settings=defaults)

    return prefixed_get_setting


class PrefixedSettings:

    def __init__(self, prefix, defaults):
        self._prefix = prefix
        self._defaults = defaults
        setattr(self, prefix, defaults)

    def __str__(self):
        return '{0._prefix}: {0._defaults}'.format(self)


# Internal helper functions


def derive_top_level_package_name(level=1):
    """Return top level package name.

    Args:
        level (int): How many levels down the stack the caller is from
            here. 1 indicates this function is being called from module
            scope, 2 indicates this function is being called from
            another function, etc.

    This will get the package name of the module containing the caller.
    It will then check if the package name contains dots and return the
    first segment.

    If this is called indirectly--e.g., via :func:`init_settings`--the
    ``level`` has to be adjusted accordingly.

    """
    frame = inspect.stack()[level][0]
    package = frame.f_globals['__package__']
    package = package.split('.', 1)[0]
    return package


def get_module_globals(level=2):
    frame = inspect.stack()[level][0]
    return frame.f_globals
