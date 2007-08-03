##############################################################################
#
# Copyright (c) 2004 Zope Corporation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################
"""Relation index tests
"""
import unittest
from zope.testing import doctest
import zope.testing.module

def setUp(test):
    zope.testing.module.setUp(test, 'zc.relation.DOCTESTS')

def tearDown(test):
    db = test.globs.get('db')
    if db is not None:
        db.close()
    zope.testing.module.tearDown(test)

def test_suite():
    res = unittest.TestSuite((
        doctest.DocFileSuite(
            'README.txt',
            setUp=setUp, tearDown=tearDown,
            optionflags=doctest.INTERPRET_FOOTNOTES),
        doctest.DocFileSuite(
            'tokens.txt',
            setUp=setUp, tearDown=tearDown,
            optionflags=doctest.INTERPRET_FOOTNOTES),
         doctest.DocFileSuite(
             'searchindex.txt',
             setUp=setUp, tearDown=tearDown,
             optionflags=doctest.INTERPRET_FOOTNOTES),
#         doctest.DocFileSuite(
#             'optimization.txt',
#             setUp=setUp, tearDown=tearDown,
#             optionflags=doctest.INTERPRET_FOOTNOTES),
#         doctest.DocFileSuite(
#             'administration.txt',
#             setUp=setUp, tearDown=tearDown,
#             optionflags=doctest.INTERPRET_FOOTNOTES),
        ))
    return res
