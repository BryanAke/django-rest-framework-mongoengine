from datetime import datetime 
import mongoengine as me 
from unittest import TestCase
from bson import objectid

from rest_framework_mongoengine.serializers import DocumentSerializer
from rest_framework import serializers as s


class Job(me.Document):
    title = me.StringField()
    status = me.StringField(choices=('draft', 'published'))
    notes = me.StringField(required=False)
    on = me.DateTimeField(default=datetime.utcnow)
    weight = me.IntField(default=0)


class JobSerializer(DocumentSerializer):
    id = s.Field()
    title = s.CharField()
    sort_weight = s.IntegerField(source='weight')


    class Meta:
        model = Job 
        fields = ('id', 'title','status', 'sort_weight')



class TestReadonlyRestore(TestCase):

    def test_restore_object(self):
        job = Job(title='original title', status='draft', notes='secure')
        data = {
            'title': 'updated title ...',
            'status': 'published',  # this one is read only
            'notes': 'hacked', # this field should not update
            'sort_weight': 10 # mapped to a field with differet name
        }

        serializer = JobSerializer(job, data=data, partial=True)

        self.assertTrue(serializer.is_valid())
        obj = serializer.object 
        self.assertEqual(data['title'], obj.title)
        self.assertEqual('draft', obj.status)
        self.assertEqual('secure', obj.notes)

        self.assertEqual(10, obj.weight)





# Testing restoring embedded property 

class Location(me.EmbeddedDocument):
    city = me.StringField()

# list of 
class Category(me.EmbeddedDocument):
    id = me.StringField()
    counter = me.IntField(default=0, required=True)


class Secret(me.EmbeddedDocument):
    key = me.StringField()

class SomeObject(me.Document):
    name = me.StringField()
    loc = me.EmbeddedDocumentField('Location')
    categories = me.ListField(me.EmbeddedDocumentField(Category))
    codes = me.ListField(me.EmbeddedDocumentField(Secret))


class LocationSerializer(DocumentSerializer):
    city = s.CharField()

    class Meta:
        model = Location

class CategorySerializer(DocumentSerializer):
    id = s.CharField(max_length=24)
    class Meta:
        model = Category
        fields = ('id',)

class SomeObjectSerializer(DocumentSerializer):
    location = LocationSerializer(source='loc')
    categories = CategorySerializer()

    class Meta:
        model = SomeObject
        fields = ('name', 'location', 'categories')


class TestCreateEmbedded(TestCase):
    def setUp(self):
        self.data = {
            'name': 'some anme', 
            'location': {
                'city': 'Toronto'
            }, 
            'categories': [{'id': 'cat1'}, {'id': 'category_2', 'counter': 666}], 
            'codes': [{'key': 'mykey1'}]
        }

    def test_validate_and_create(self):
        #passing values to serializer via data paramter
        #should validate data,
        serializer = SomeObjectSerializer(data=self.data)    
        self.assertTrue(serializer.is_valid())
        obj = serializer.object 

        self.assertEqual(self.data['name'], obj.name )
        self.assertEqual('Toronto', obj.loc.city )

        self.assertEqual(2, len(obj.categories))
        self.assertEqual('category_2', obj.categories[1].id)
        # counter is not listed in serializer fields, cannot be updated
        self.assertEqual(0, obj.categories[1].counter) 

        # codes are not listed, should not be updatable
        self.assertEqual(0, len(obj.codes))

    def test_invalid_data(self):
        #serializer fed invalid data should not populate a model.
        self.assertTrue(False)

    def test_update(self):
        #passing data to serializer populated by an instance
        #values specified should should populate correctly.
        data = self.data
        instance = SomeObject(
            name='original', 
            loc=Location(city="New York"), 
            categories=[Category(id='orig1', counter=777)], 
            codes=[Secret(key='confidential123')]
        )
        serializer = SomeObjectSerializer(instance, data=data, partial=True)
         
        # self.assertTrue(serializer.is_valid())
        if not serializer.is_valid():
            print 'errors: %s' % serializer._errors
            assert False, 'errors'

        obj = serializer.object

        self.assertEqual(data['name'], obj.name )
        self.assertEqual('Toronto', obj.loc.city )

        # codes is not listed, should not be updatable
        self.assertEqual(1, len(obj.codes[0]))
        self.assertEqual('confidential123', obj.codes[0].key) # should keep original val

        self.assertEqual(2, len(obj.categories))
        self.assertEqual('category_2', obj.categories[1].id)
        self.assertEqual(0, obj.categories[1].counter)

    def test_custom_field_overriding(self):
        #we should be able to provide a field to override the default mapping.
        self.assertTrue(False)

    def test_field_population(self):
        #fields should be generated and populated lazily based on model.
        self.assertTrue(False)

    def test_declared_fields(self):
        #fields declared on serializer should be instantiated as defined, not based on defaults from model.
        self.assertTrue(False)

    def test_extra_kwargs(self):
        #Extra kwargs defined in Serializer Meta should be passed to fields.
        self.assertTrue(False)

    def test_depth_flow(self):
        #Depth options.
        self.assertTrue(False)

    def test_no_dereference(self):
        #Option to avoid dereferencing objects, which would fire additional queries.
        self.assertTrue(False)

