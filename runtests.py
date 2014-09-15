#!/usr/bin/env python
import os, sys
from django.conf import settings

settings.configure(
    DEBUG=True,
    DATABASES={
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
        }
    },
    ROOT_URLCONF='urls',
    INSTALLED_APPS=(
        'django.contrib.auth',
        'django.contrib.contenttypes',
        'django.contrib.sessions',
        'django.contrib.admin',
        'arcutils',
    ),
    LDAP={
        "default": {
            "host": "ldap://ldap-login.oit.pdx.edu",
            "username": "",
            "password": "",
            "search_dn": "ou=people,dc=pdx,dc=edu",
        }
    }
)


from django.test.simple import DjangoTestSuiteRunner
test_runner = DjangoTestSuiteRunner(verbosity=1)
failures = test_runner.run_tests(['arcutils', ])
if failures:
    sys.exit(failures)
