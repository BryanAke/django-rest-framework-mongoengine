from mongoengine.fields import ReferenceField, ObjectIdField

RESOLVE_URI = False


def NAMESPACE(type, id):
    return '{0}:{1}'.format(type, id)


class Namespaced(object):
    def __init__(self, lookup=NAMESPACE, uri=True):
        self.lookup = lookup
        self.uri = uri

    def __enter__(self):
        global NAMESPACE, RESOLVE_URI
        self._reverse = NAMESPACE
        self._resolve_uri = RESOLVE_URI
        NAMESPACE = self.lookup
        RESOLVE_URI = self.uri

    def __exit__(self, type, value, traceback):
        global NAMESPACE, RESOLVE_URI
        NAMESPACE = self._reverse
        RESOLVE_URI = self._resolve_uri


def ref_to_mongo(func):
    def to_mongo(self, document):
        id = func(self, document)
        if not RESOLVE_URI:
            return id
        else:
            doc_type = getattr(self.document_type, '_class_name', self.name)
            return NAMESPACE(doc_type, id)

    return to_mongo


ReferenceField.to_mongo = ref_to_mongo(ReferenceField.to_mongo)
ObjectIdField.to_mongo = ref_to_mongo(ObjectIdField.to_mongo)