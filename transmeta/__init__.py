import copy

from django.db import models
from django.db.models.fields import NOT_PROVIDED
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import get_language, string_concat

LANGUAGE_CODE = 0
LANGUAGE_NAME = 1


def get_real_fieldname(field, lang=None):
    if lang is None:
       lang = get_language()
    return str('%s_%s' % (field, lang.replace('-', '_')))


def get_fallback_fieldname(field):
    return get_real_fieldname(field, lang=fallback_language())


def get_real_fieldname_in_each_language(field):
    return [get_real_fieldname(field, lang[LANGUAGE_CODE])
            for lang in settings.LANGUAGES]


def canonical_fieldname(db_field):
    """ all "description_en", "description_fr", etc. field names will return "description" """
    return getattr(db_field, 'original_fieldname', db_field.name) # original_fieldname is set by transmeta


def fallback_language():
    """ returns fallback language """
    return getattr(settings, 'TRANSMETA_DEFAULT_LANGUAGE', \
                   settings.LANGUAGE_CODE)


def get_all_translatable_fields(model):
    """ returns all translatable fields in a model (including superclasses ones) """
    model_trans_fields = set(getattr(model._meta, 'translatable_fields', []))
    for parent in model._meta.parents:
        parent_trans_fields = getattr(parent._meta, 'translatable_fields', [])
        model_trans_fields.update(parent_trans_fields)
    return tuple(model_trans_fields)


def default_value_getter(field):
    '''
    When accessing to the name of the field itself, the value
    in the current language will be returned. Unless it's set,
    the value in the default language will be returned.
    '''

    def default_value_func_getter(self):
        attname = lambda x: get_real_fieldname(field, x)

        language = None
        current_language = get_language()

        if getattr(self, attname(current_language), None):
            language = current_language
        elif getattr(self, attname(current_language[:2]), None):
            language = current_language[:2]
        else:
            try:
                default_language = getattr(self, getattr(self._meta, 'default_language_field'))
                if not default_language:
                    raise
            except:
                default_language = fallback_language()

            if getattr(self, attname(default_language), None):
                language = default_language
            else:
                language = default_language[:2]

        if language:
            return getattr(self, attname(language))

    return default_value_func_getter


def default_value_setter(field):
    '''
    When setting to the name of the field itself, the value
    in the current language will be set.
    '''

    def default_value_func_setter(self, value):
        attname = lambda x: get_real_fieldname(field, x)

        language = None
        current_language = get_language()

        if hasattr(self, attname(current_language)):
            language = current_language
        elif hasattr(self, attname(current_language[:2])):
            language = current_language[:2]
        else:
            try:
                default_language = getattr(self, getattr(self._meta, 'default_language_field'))
                if not default_language:
                    raise
            except:
                default_language = fallback_language()

            if hasattr(self, attname(default_language)):
                language = default_language
            elif hasattr(self, attname(default_language[:2])):
                language = default_language[:2]

        if language:
            setattr(self, attname(language), value)

    return default_value_func_setter


class TransMeta(models.base.ModelBase):
    '''
    Metaclass that allow a django field, to store a value for
    every language. The syntax to us it is next:

        class MyClass(models.Model):
            __metaclass__ transmeta.TransMeta

            my_field = models.CharField(max_length=20)
            my_i18n_field = models.CharField(max_length=30)

            # default_lang below is optional, used with default_language_field in Meta class
            # and it can has whatever name you want
            # the value must be set in your application !
            default_lang = models.CharField(max_length=5,
                choices=settings.LANGUAGES, blank=True, verbose_name=_("Default language"))

            class Meta:
                translate = ('my_i18n_field',)

                # name of the field which will store the default lang for this object, used 
                # in setter if no field for current language, and in getter if field is empty 
                # for currentlanguage. If not present or no field for it, then default language
                # code is used (settings.TRANSMETA_DEFAULT_LANGUAGE or LANGUAGE_CODE)
                default_language_field = 'default_lang'

    Then we'll be able to access a specific language by
    <field_name>_<language_code>. If just <field_name> is
    accessed, we'll get the value of the current language,
    or if null, the value in the default_language_field
    language if set, else the value in the default language.
    '''

    def __new__(cls, name, bases, attrs):
        translate_verbose_names = True
        if 'Meta' in attrs and hasattr(attrs['Meta'], 'translate_verbose_names'):
            translate_verbose_names = attrs['Meta'].translate_verbose_names
            delattr(attrs['Meta'], 'translate_verbose_names')
        if 'Meta' in attrs and hasattr(attrs['Meta'], 'translate'):
            fields = attrs['Meta'].translate
            delattr(attrs['Meta'], 'translate')
        else:
            new_class = super(TransMeta, cls).__new__(cls, name, bases, attrs)
            # we inherits possible translatable_fields from superclasses
            abstract_model_bases = [base for base in bases if hasattr(base, '_meta') \
                                    and base._meta.abstract]
            translatable_fields = []
            for base in abstract_model_bases:
                if hasattr(base._meta, 'translatable_fields'):
                    translatable_fields.extend(list(base._meta.translatable_fields))
            new_class._meta.translatable_fields = tuple(translatable_fields)
            return new_class

        if not isinstance(fields, tuple):
            raise ImproperlyConfigured("Meta's translate attribute must be a tuple")

        default_language = fallback_language()

        for field in fields:
            if not field in attrs or \
               not isinstance(attrs[field], models.fields.Field):
                    raise ImproperlyConfigured(
                        "There is no field %(field)s in model %(name)s, "\
                        "as specified in Meta's translate attribute" % \
                        dict(field=field, name=name))
            original_attr = attrs[field]
            for lang in settings.LANGUAGES:
                lang_code = lang[LANGUAGE_CODE]
                lang_attr = copy.copy(original_attr)
                lang_attr.original_fieldname = field
                lang_attr_name = get_real_fieldname(field, lang_code)
                if lang_code != default_language:
                    # only will be required for default language
                    if not lang_attr.null and lang_attr.default is NOT_PROVIDED:
                        lang_attr.null = True
                    if not lang_attr.blank:
                        lang_attr.blank = True
                if lang_attr.verbose_name and translate_verbose_names:
                    lang_attr.verbose_name = string_concat(lang_attr.verbose_name, u' (%s)' % lang_code)
                attrs[lang_attr_name] = lang_attr
            del attrs[field]
            attrs[field] = property(default_value_getter(field), default_value_setter(field))

        default_language_field = None
        if 'Meta' in attrs and hasattr(attrs['Meta'], 'default_language_field'):
            default_language_field = attrs['Meta'].default_language_field
            if not default_language_field in attrs:
                default_language_field = None
            delattr(attrs['Meta'], 'default_language_field')

        new_class = super(TransMeta, cls).__new__(cls, name, bases, attrs)
        if hasattr(new_class, '_meta'):
            new_class._meta.translatable_fields = fields
            if default_language_field:
                new_class._meta.default_language_field = default_language_field
        return new_class
