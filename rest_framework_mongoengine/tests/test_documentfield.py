__author__ = 'bake3'
from rest_framework_mongoengine.fields import DocumentField

import mongoengine as me
from unittest import TestCase

class TestDocumentSerializer(TestCase):
    def setUp(self):
        self.data = {
            'name': 'some anme',
            'location': {
                'city': 'Toronto'
            },
            'categories': [{'id': 'cat1'}, {'id': 'category_2', 'counter': 666}],
            'codes': [{'key': 'mykey1'}]
        }

    def test_lazy_fields(self):
        self.assertEqual(0, 1)


    def test_fields_from_serializer(self):
        self.assertTrue(False)