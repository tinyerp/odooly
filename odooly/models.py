import re
from string import Formatter

from .helpers import base_method_params, issearchdomain, memoize,  partial, searchargs

__all__ = ["BaseModel", "BaseRecord", "Id1", "Ids", "Model", "Record", "RecordList"]


class Ids(list):
    __slots__ = ()


class Id1(int):
    __slots__ = ()


class BaseModel:

    def sudo(self, user=None):
        """Attach to the provided user, or Superuser."""
        return self.with_env(self.env.sudo(user=user))

    def with_context(self, *args, **kwargs):
        """Attach to an extended context."""
        context = dict(args[0] if args else self.env.context, **kwargs)
        return self.with_env(self.env(context=context))

    def with_odoo(self):
        """Attach to an ``odoo.api.Environment``.

        Use same (db_name, uid, context) as current ``Env``.
        Only available in ``local`` mode.
        """
        return self.with_env(self.env.odoo_env)


class Model(BaseModel):
    """The class for Odoo models."""

    def __new__(cls, env, name):
        return env[name]

    @classmethod
    def _new(cls, env, name):
        m = object.__new__(cls)
        (m.env, m._name) = (env, name)
        m._execute = partial(env.execute, name)
        return m

    def __repr__(self):
        return f"<Model '{self._name}'>"

    def with_env(self, env):
        """Attach to the provided environment."""
        return env[self._name]

    def keys(self):
        """Return the keys of the model."""
        return self._keys

    def fields(self, names=None, attributes=None):
        """Return a dictionary of the fields of the model.

        Optional argument `names` is a sequence of field names or
        a space separated string of these names.
        If omitted, all fields are returned.
        Optional argument `attributes` is a sequence of attributes
        or a space separated string of these attributes.
        If omitted, all attributes are returned.
        """
        if isinstance(names, str):
            names = names.split()
        if isinstance(attributes, str):
            attributes = attributes.split()
        if names is None:
            if attributes is None:
                return self._fields
            return {fld: {att: val
                          for (att, val) in vals.items() if att in attributes}
                    for (fld, vals) in self._fields.items()}
        if attributes is None:
            return {fld: vals
                    for (fld, vals) in self._fields.items() if fld in names}
        return {fld: {att: val
                      for (att, val) in vals.items() if att in attributes}
                for (fld, vals) in self._fields.items() if fld in names}

    def field(self, name):
        """Return the field properties for field `name`."""
        return self._fields[name]

    @staticmethod
    def _parse_doc_methods(doc_dict):
        methods = doc_dict.get('methods') or {}
        result = []
        for key, vals in methods.items():
            arg_names = [*vals['parameters']]
            if 'model' not in vals.get('api', ()):
                arg_names.insert(0, 'ids')
            result.append((key, arg_names))
        return result

    def _methods(self, name=''):
        """List methods and arguments.

        Argument `name` is a pattern to filter the methods returned.
        If omitted, all methods are returned.
        """
        try:
            method_params = self._parse_doc_methods(self._doc)
        except Exception:
            method_params = base_method_params
        return {key: args for (key, args) in method_params if name in key}

    def access(self, mode="read"):
        """Check if the user has access to this model.

        Optional argument `mode` is the access mode to check.  Valid values
        are ``read``, ``write``, ``create`` and ``unlink``. If omitted,
        the ``read`` mode is checked.  Return a boolean.
        """
        return self.env.access(self._name, mode)

    def browse(self, ids=()):
        """Return a :class:`Record` or a :class:`RecordList`.

        The argument `ids` accepts a single integer ``id`` or a list of ids.
        If it is a single integer, the return value is a :class:`Record`.
        Otherwise, the return value is a :class:`RecordList`.
        """
        if isinstance(ids, int) or (len(ids) == 2 and isinstance(ids[1], str)):
            return Record(self, ids)
        return RecordList(self, ids)

    def search(self, domain, **kwargs):
        """Search for records in the `domain`."""
        if kwargs.get('count'):
            return self.search_count(domain)
        return RecordList._prepared(self, domain, kwargs)

    def search_count(self, domain=None):
        """Count the records in the `domain`."""
        return self._execute('search_count', domain or [])

    def search_read(self, domain=None, fields=None, **kwargs):
        """Combine search and read."""
        fields, fmt = self._parse_format(fields, browse=False)
        res = self._execute('search_read', domain or [], fields, **kwargs)
        return fmt(res)

    def get(self, domain, *args, **kwargs):
        """Return a single :class:`Record`.

        The argument `domain` accepts a single integer ``id`` or a search
        domain, or an external ID ``xml_id``.  The return value is a
        :class:`Record` or None.  If multiple records are found,
        a ``ValueError`` is raised.
        """
        if args or kwargs:
            # Passthrough for env['ir.default'].get and alike
            return self._execute('get', domain, *args, **kwargs)
        if isinstance(domain, int):   # a single id
            return Record(self, domain)
        if isinstance(domain, str):  # lookup the xml_id
            rec = self.env.ref(domain)
            if not rec:
                return None
            assert rec._model is self, f'Model mismatch {rec!r} {self!r}'
            return rec
        assert issearchdomain(domain)       # a search domain
        if len(ids := self._execute('search', domain)) > 1:
            raise ValueError(f'domain matches too many records ({len(ids)})')
        return Record(self, ids[0]) if ids else None

    def create(self, values):
        """Create one :class:`Record` or many.

        The argument `values` is a dictionary of values which are used to
        create the record.  Relationship fields `one2many` and `many2many`
        accept either a list of ids or a RecordList or the extended Odoo
        syntax.  Relationship fields `many2one` and `reference` accept
        either a Record or the Odoo syntax.  It can create multiple records.

        The newly created :class:`Record` is returned, or :class:`RecordList`.
        """
        if hasattr(values, "items"):
            values, nb = self._unbrowse_values(values), 1
        else:  # Odoo >= 12
            values, nb = [self._unbrowse_values(vals) for vals in values], len(values)
        new_ids = self._execute('create', values)
        if not new_ids and self.env.client._use_call_button:
            return self.search([], order='id DESC', limit=nb)
        return self.browse(new_ids)

    def read(self, *params, **kwargs):
        """Wrapper for ``client.execute(model, 'read', [...], ('a', 'b'))``.

        The first argument is a list of ids ``[1, 3]`` or a single id ``42``
        or a search domain.

        The second argument, `fields`, accepts:
         - a single field: ``'first_name'``
         - a tuple of fields: ``('street', 'city')``
         - a space separated list: ``'street city'``
         - a format string: ``'{street} {city}'``

        If `fields` is omitted, all fields are read.

        If `domain` is a single id, then:
         - return a single value if a single field is requested.
         - return a string if a format spec is passed in the `fields` argument.
         - else, return a dictionary.

        If `domain` is not a single id, the returned value is a list of items.
        Each item complies with the rules of the previous paragraph.

        The optional keyword arguments `offset`, `limit` and `order` are
        used to restrict the search.
        """
        arg = params[1] if len(params) > 1 else None
        fields, fmt = self._parse_format(arg, browse=False)
        if arg is not None:
            params = (params[0], fields) + params[2:]
        res = self._execute('read', *params, **kwargs)
        return fmt(res) if isinstance(res, list) else fmt([res])[0]

    def _parse_format(self, arg, browse=True):
        if not isinstance(arg, str):
            fields, formatter = arg, None
        elif '}' in arg:
            fields = [re.match(r'\w+', tup[1]).group(0)
                      for tup in Formatter().parse(arg) if tup[1]]
            formatter = arg.format_map
        else:  # transform: "zip city" --> ["zip", "city"]
            fields = arg.split()
            formatter = (lambda d: d[fields[0]]) if len(fields) == 1 else None

        def lst_format(values):
            return [(val and formatter(val)) for val in values]

        if browse:
            if not formatter:
                formatter = self._browse_values
            elif fields == arg.split():
                if 'relation' in (fspec := self.field(fields[0])):
                    rel_model = self.env._get(fspec['relation'], False)
                    if fspec['type'] == 'many2one':
                        m_browse = partial(RecordList, rel_model)
                    else:

                        def m_browse(values):
                            if not values:
                                return RecordList(rel_model, ())
                            return [RecordList(rel_model, val or ()) for val in values]

                    def lst_format(values):  # noqa
                        return m_browse([(val and formatter(val)) for val in values])

                elif fspec['type'] == 'reference':

                    def formatter(dic):
                        if not (value := dic[fields[0]]):
                            return value
                        (res_model, res_id) = value.split(',')
                        rel_model = self.env._get(res_model, False)
                        return Record(rel_model, int(res_id))
        elif not formatter:
            def lst_format(values):
                return values

        return fields, lst_format

    def _browse_values(self, values):
        """Wrap the values of a Record.

        The argument `values` is a dictionary of values read from a Record.
        When the field type is relational (many2one, one2many or many2many),
        the value is wrapped in a Record or a RecordList.
        Return a dictionary with the same keys as the `values` argument.
        """
        for (key, value) in values.items():
            if key == 'id' or value is False or hasattr(value, 'id'):
                continue
            if (field := self._fields[key])['type'] == 'reference':
                (res_model, res_id) = value.split(',')
                value = int(res_id)
            elif 'relation' in field:
                res_model = field['relation']
            else:
                continue
            rel_model = self.env._get(res_model, False)
            values[key] = rel_model.browse(value)
        return values

    def _unbrowse_values(self, values):
        """Unwrap the id of Record and RecordList."""
        new_values = values.copy()
        for (key, value) in values.items():
            many = self._fields[key]['type'] in {'one2many', 'many2many'}
            if hasattr(value, 'id'):
                if self._fields[key]['type'] == 'reference':
                    new_values[key] = f'{value._name},{value.id}'
                else:
                    fld_model = self._fields[key].get('relation')
                    if fld_model and value._name != fld_model:
                        raise TypeError(f"Mixing apples and oranges: {fld_model} <> {value._name}")
                    new_values[key] = value = value.id and (value.ids if many else int(value))
            if many:
                if not value:
                    new_values[key] = [(6, 0, [])]
                elif isinstance(value[0], int):
                    new_values[key] = [(6, 0, value)]
        return new_values

    def _get_external_ids(self, ids=None):
        """Retrieve the External IDs of the records.

        Return a dictionary with keys being the fully qualified
        External IDs, and values the ``Record`` entries.
        """
        search_domain = [('model', '=', self._name)]
        if ids is not None:
            search_domain.append(('res_id', 'in', ids))
        existing = self.env._get('ir.model.data', False).read(search_domain, 'module name res_id')
        return {f"{rec['module']}.{rec['name']}": self.get(rec['res_id']) for rec in existing}

    def __getattr__(self, attr):
        if attr == '_fields':
            if (vals := self.env._cache_get((attr, self._name))) is None:
                if self.__dict__.get('_doc'):
                    vals = self._doc['fields']
                else:
                    vals = self._execute('fields_get')
                self.env._cache_set((attr, self._name), vals)
            return memoize(self, attr, vals)
        if attr == '_keys':
            return memoize(self, attr, sorted(self._fields))
        if attr == '_doc':
            return memoize(self, attr, self.env._doc(self._name) if self.env._doc else None)
        if attr.startswith('_'):
            raise AttributeError(f"'Model' object has no attribute {attr!r}")

        def wrapper(self, *params, **kwargs):
            """Wrapper for client.execute({!r}, {!r}, *params, **kwargs)."""
            return self._execute(attr, *params, **kwargs)
        return memoize(self, attr, wrapper, (self._name, attr))


class BaseRecord(BaseModel):

    def __init__(self, res_model, arg):
        attrs = {'_name': res_model._name, '_model': res_model,
                 'env': res_model.env, '_execute': res_model._execute}
        # Bypass __setattr__ method
        self.__dict__.update(attrs)

    def __repr__(self):
        ids = f'length={len(self.ids)}' if len(self.ids) > 6 else self.id
        return f"<{self.__class__.__name__} '{self._name},{ids}'>"

    def __bool__(self):
        return bool(self.ids)

    def __len__(self):
        return len(self.ids)

    def __getitem__(self, key):
        idname = self._idnames[key]
        return self._model.browse(idname) if idname is not False else False

    def __iter__(self):
        yield from (Record(self._model, idname) for idname in self._idnames)

    def __contains__(self, item):
        if isinstance(item, BaseRecord):
            item._check_model(self, 'in')
            return len(item) == 1 and item.ids[0] in self.ids

    def __add__(self, other):
        return self.concat(other)

    def __sub__(self, other):
        self._check_model(other, '-')
        other_ids = {*other.ids}
        ids = [idn for (id_, idn) in zip(self.ids, self._idnames)
               if id_ not in other_ids]
        return RecordList(self._model, ids)

    def __and__(self, other):
        self._check_model(other, '&')
        other_ids = {*other.ids}
        self_set = self.union()
        ids = [idn for (id_, idn) in zip(self_set.ids, self_set._idnames)
               if id_ in other_ids]
        return RecordList(self._model, ids)

    def __or__(self, other):
        return self.union(other)

    def __eq__(self, other):
        return (self.__class__ is other.__class__ and
                self.ids == other.ids and self._model is other._model)

    def __ne__(self, other):
        return not self == other

    def __lt__(self, other):
        self._check_model(other, '<')
        return {*self.ids} < {*other.ids}

    def __le__(self, other):
        self._check_model(other, '<=')
        return {*self.ids}.issubset(other.ids)

    def __gt__(self, other):
        self._check_model(other, '>')
        return {*self.ids} > {*other.ids}

    def __ge__(self, other):
        self._check_model(other, '>=')
        return {*self.ids}.issuperset(other.ids)

    def __int__(self):
        return int(self.ensure_one().id)

    @property
    def _keys(self):
        return self._model._keys

    @property
    def _fields(self):
        return self._model._fields

    def _methods(self, name=''):
        return self._model._methods(name)

    def _invalidate_cache(self):
        pass

    def ensure_one(self):
        """Return the single record in this recordset.

        Raise a ValueError it recordset has more records or is empty.
        """
        if self.id and not isinstance(self.id, list):
            return self
        if len((recs := self.union()).id) == 1:
            return recs[0]
        raise ValueError(f"Expected singleton: {self}")

    def exists(self):
        """Return a subset of records that exist."""
        if self.env.client.version_info < 19.0:
            method, arg = 'exists', self.union().ids
        else:
            # Beware that it might be wrong, if `search` method is overloaded.
            # This is the case for 'ir.attachment' for example.
            method, arg = 'search', [('id', 'in', self.union().ids)]
        ids = self.ids and self._execute(method, arg, context={'active_test': False})
        if ids and not isinstance(self.id, list):
            ids = ids[0]
        return self._model.browse(ids)

    def get_metadata(self):
        """Read the metadata of the record(s)

        Return a dictionary of values.
        """
        return self._execute('get_metadata', self.ids)

    def with_env(self, env):
        return env[self._name].browse(self.id)

    def _check_model(self, other, oper):
        if not (isinstance(other, BaseRecord) and self._model is other._model):
            raise TypeError(f"Mixing apples and oranges: {self} {oper} {other}")

    def _concat_ids(self, args):
        ids = [*self._idnames]
        for other in args:
            self._check_model(other, '+')
            ids.extend(other._idnames)
        return ids

    def concat(self, *args):
        """Return the concatenation of all records."""
        ids = self._concat_ids(args)
        return RecordList(self._model, ids)

    def union(self, *args):
        """Return the union of all records.

        Preserve first occurence order.
        """
        ids = self._concat_ids(args)
        if len(ids) > 1:
            seen = {*()}
            uniqids = []
            for idn in ids:
                id_, name = idn if isinstance(idn, (list, tuple)) else (idn, None)
                if id_ not in seen and not seen.add(id_) and id_:
                    uniqids.append((id_, name) if name else id_)
            ids = uniqids
        return RecordList(self._model, ids)

    @classmethod
    def _union(cls, args):
        if hasattr(args, 'union'):
            return args.union()
        if args and isinstance(args, list) and hasattr(args[0], 'union'):
            return cls.union(*args)
        return args

    def _filter(self, attrs):
        ids, rels = [], []
        for (rec, rel) in zip(self, self.read(attrs.pop(0))):
            if rel and (not hasattr(rel, 'ids') or rel.id):
                ids.append(rec._idnames[0])
                rels.append(rel)
        if ids and attrs:
            relids = {idn[0] for idn in BaseRecord.union(*rels)._filter(attrs)}
            ids = [rec_id for (rec_id, rel) in zip(ids, rels)
                   if any(rel_id in relids for rel_id in rel.ids)]
        return ids

    def mapped(self, func):
        """Apply ``func`` on all records."""
        if callable(func):
            return self._union([func(rec) for rec in self])
        # func is a path
        vals = self[:]
        for name in func.split('.'):
            vals = self._union(vals.read(name))
        return vals

    def filtered(self, func):
        """Select the records such that ``func(rec)`` is true.

        As an alternative ``func`` can be a search domain (list)
        to search among the records.
        """
        if callable(func):
            ids = [rec._idnames[0] for rec in self if func(rec)]
        elif isinstance(func, list):
            return self & self._model.search([('id', 'in', self.ids)] + func)
        else:
            ids = self[:]._filter(func.split('.')) if func else self._idnames
        return RecordList(self._model, ids)

    def sorted(self, key=None, reverse=False):
        """Return the records sorted by ``key``."""
        if len((recs := self.union()).ids) < 2:
            return recs
        if key is None:
            idnames = dict(zip(recs.ids, recs._idnames))
            recs = self._model.search([('id', 'in', recs.ids)])
            ids = [idnames[id_] for id_ in recs.ids]
        elif isinstance(key, str):
            vals = sorted(zip(recs.read(key), recs._idnames))
            ids = [idn for (__, idn) in vals]
        else:
            ids = [rec._idnames[0] for rec in sorted(recs, key=key)]
        return RecordList(self._model, ids[::-1] if reverse else ids)

    def write(self, values):
        """Write the `values` in the record(s).

        `values` is a dictionary of values.
        See :meth:`Model.create` for details.
        """
        if not self.id:
            return True
        values = self._model._unbrowse_values(values)
        self._invalidate_cache()
        return self._execute('write', self.ids, values)

    def unlink(self):
        """Delete the record(s) from the database."""
        if not self.id:
            return True
        self._invalidate_cache()
        return self._execute('unlink', self.ids)


class RecordList(BaseRecord):
    """A sequence of Odoo :class:`Record`.

    It has a similar API as the :class:`Record` class, but for a list of
    records.  The attributes of the ``RecordList`` are read-only, and they
    return list of attribute values in the same order.  The ``many2one``,
    ``one2many`` and ``many2many`` attributes are wrapped in ``RecordList``
    and list of ``RecordList`` objects.  Use the method ``RecordList.write``
    to assign a single value to all the selected records.
    """

    def __init__(self, res_model, arg, search=None):
        super().__init__(res_model, arg)
        if search is None:
            idnames = arg or ()
            ids = Ids(idnames)
            for index, id_ in enumerate(arg):
                if isinstance(id_, (list, tuple)):
                    ids[index] = id_ = id_[0]
                assert isinstance(id_, int), repr(id_)
            self.__dict__.update({'id': ids, 'ids': ids, '_idnames': idnames, '_search_args': None})
        else:
            self.__dict__['_search_args'] = {'model': res_model, **search}

    @classmethod
    def _prepared(cls, res_model, domain, params):
        [domain] = searchargs((domain,))
        return cls(res_model, None, search={'domain': domain, **params})

    def refresh(self):
        """Reset :class:`RecordList` content."""
        if self._search_args:
            for key in 'id', 'ids', '_idnames':
                self.__dict__.pop(key, None)

    def __getitem__(self, key):
        if 'id' not in self.__dict__ and isinstance(key, int) and key >= 0:
            self, key = self[key:key+1], 0
        if 'id' in self.__dict__ or (getattr(key, 'start', -1) or 0) < 0:
            return super().__getitem__(key)
        is_stop_positive = key.stop is not None and key.stop >= 0
        search_args = {**self._search_args}
        new_offset, new_stop = key.start or 0, search_args.get('limit', None)
        if is_stop_positive:
            new_stop = key.stop if new_stop is None else min(new_stop, key.stop)
        if new_stop is not None:
            search_args['limit'] = limit = new_stop - new_offset
            if limit <= 0:
                return RecordList(self._model, [])
        if new_offset:
            search_args['offset'] = (search_args.get('offset') or 0) + new_offset
        result = RecordList(self._model, None, search=search_args)
        if (is_stop_positive or key.stop is None) and key.step in {1, None}:
            return result
        key = slice(None, limit if is_stop_positive else key.stop, key.step)
        return super(RecordList, result).__getitem__(key)

    def with_env(self, env):
        if 'id' in self.__dict__:
            return super().with_env(env)
        return RecordList(env[self._name], None, {**self._search_args})

    def read(self, fields=None):
        """Read the `fields` of the :class:`RecordList`.

        The argument `fields` accepts different kinds of values.
        See :meth:`Model.read` for details.
        """
        fields, fmt = self._model._parse_format(fields)

        if fields == ['id']:
            values = [{'id': res_id} for res_id in self.ids]
        elif 'id' not in self.__dict__:
            params = {**self._search_args}
            values = params.pop('model').search_read(params.pop('domain'), fields, **params)
            ids = idnames = [val['id'] for val in values]
            if values and 'display_name' in values[0]:
                idnames = [(val['id'], val['display_name']) for val in values]
            self.__dict__.update({'id': Ids(ids), 'ids': Ids(ids), '_idnames': idnames})
        else:
            values = self._model.read(self.ids, fields, order=True) if self.ids else []

        return fmt(values)

    def copy(self, default=None):
        """Copy records and return :class:`RecordList`.

        The optional argument `default` is a mapping which overrides some
        values of the new records.

        Supported since Odoo 18.
        """
        default = default and self._model._unbrowse_values(default)
        new_ids = self._execute('copy', self.ids, default)
        return RecordList(self._model, new_ids)

    @property
    def _external_id(self):
        """Retrieve the External IDs of the :class:`RecordList`.

        Return the fully qualified External IDs with default value
        False if there's none.  If multiple IDs exist for a record,
        only one of them is returned (randomly).
        """
        xml_ids = {r.id: xml_id for (xml_id, r) in
                   self._model._get_external_ids(self.ids).items()}
        return [xml_ids.get(res_id, False) for res_id in self.id]

    def __getattr__(self, attr):
        if attr in {'id', 'ids', '_idnames'}:
            params = {**self._search_args}
            ids = params.pop('model')._execute('search', params.pop('domain'), **params)
            self.__dict__.update({'id': Ids(ids), 'ids': Ids(ids), '_idnames': ids})
            return self.__dict__[attr]
        if attr in self._model._keys:
            return self.read(attr)
        if attr.startswith('_'):
            errmsg = f"'RecordList' object has no attribute {attr!r}"
            raise AttributeError(errmsg)

        def wrapper(self, *params, **kwargs):
            """Wrapper for client.execute({!r}, {!r}, [...], *params, **kwargs)."""
            return self._execute(attr, self.ids, *params, **kwargs)
        return memoize(self, attr, wrapper, (self._name, attr))

    def __setattr__(self, attr, value):
        if attr in self._model._keys or attr == 'id':
            msg = f"attribute {attr!r} is read-only; use 'RecordList.write' instead."
        else:
            msg = f"has no attribute {attr!r}"
        raise AttributeError("'RecordList' object " + msg)


class Record(BaseRecord):
    """A class for all Odoo records.

    It maps any Odoo object.
    The fields can be accessed through attributes.  The changes are immediately
    sent to the server.
    The ``many2one``, ``one2many`` and ``many2many`` attributes are wrapped in
    ``Record`` and ``RecordList`` objects.  These attributes support writing
    too.
    The attributes are evaluated lazily, and they are cached in the record.
    The Record's cache is invalidated if any attribute is changed.
    """

    def __init__(self, res_model, arg):
        super().__init__(res_model, arg)
        if isinstance(arg, int):
            name, idnames = None, [arg]
        else:
            idnames = [(arg, name)] = [arg]
        attrs = {'id': Id1(arg), 'ids': Ids([arg]), '_idnames': idnames, '_cached_keys': {*()}}
        if name is not None:
            attrs['_Record__name'] = attrs['display_name'] = name
        self.__dict__.update(attrs)

    def __str__(self):
        return self.__name if self.id else 'False'

    def _get_name(self):
        try:
            name = self.display_name
        except Exception:
            name = f'{self._name},{self.id}'
        self.__dict__['_idnames'] = [(int(self.id), str(name))]
        return memoize(self, '_Record__name', str(name))

    def refresh(self):
        """Force refreshing the record's data."""
        self._invalidate_cache()

    def _invalidate_cache(self):
        self._cached_keys.discard('id')
        for key in self._cached_keys:
            delattr(self, key)
        self._cached_keys.clear()

    def _update(self, values):
        new_values = self._model._browse_values(values)
        self.__dict__.update(new_values)
        self._cached_keys.update(new_values)
        return new_values

    def read(self, fields=None):
        """Read the `fields` of the :class:`Record`.

        The argument `fields` accepts different kinds of values.
        See :meth:`Model.read` for details.
        """
        rv = self._model.read(self.id, fields)
        if rv is not None and isinstance(fields, str) and fields in self._model._keys:
            return self._update({fields: rv})[fields]
        if isinstance(rv, dict):
            return self._update(rv)
        return rv

    def copy(self, default=None):
        """Copy a record and return the new :class:`Record`.

        The optional argument `default` is a mapping which overrides some
        values of the new record.
        """
        default = default and self._model._unbrowse_values(default)
        new_id = self._execute('copy', self.id, default)
        if isinstance(new_id, list):
            [new_id] = new_id or [False]
        return Record(self._model, new_id)

    @property
    def _external_id(self):
        """Retrieve the External ID of the :class:`Record`.

        Return the fully qualified External ID of the :class:`Record`,
        with default value False if there's none.  If multiple IDs
        exist, only one of them is returned (randomly).
        """
        xml_ids = self._model._get_external_ids(self.ids)
        return [*xml_ids][0] if xml_ids else False

    def _set_external_id(self, xml_id):
        """Set the External ID of this record."""
        (mod, name) = xml_id.split('.')
        domain = ['|', '&', ('module', '=', mod), ('name', '=', name),
                  '&', ('model', '=', self._name), ('res_id', '=', self.id)]
        if self.env._get('ir.model.data', False).search(domain):
            raise ValueError(f'ID {xml_id!r} collides with another entry')
        values = {'model': self._name, 'res_id': self.id, 'module': mod, 'name': name}
        self.env._get('ir.model.data', False).create(values)

    def __getattr__(self, attr):
        if attr in self._model._keys:
            return self.read(attr)
        if attr == '_Record__name':
            return self._get_name()
        if attr.startswith('_'):
            raise AttributeError(f"'Record' object has no attribute {attr!r}")

        def wrapper(self, *params, **kwargs):
            """Wrapper for client.execute({!r}, {!r}, {:d}, *params, **kwargs)."""
            res = self._execute(attr, self.ids, *params, **kwargs)
            self._invalidate_cache()
            if isinstance(res, list) and len(res) == 1:
                return res[0]
            return res
        return memoize(self, attr, wrapper, (self._name, attr, self.id))

    def __setattr__(self, attr, value):
        if attr == '_external_id':
            return self._set_external_id(value)
        if attr not in self._model._keys:
            raise AttributeError(f"'Record' object has no attribute {attr!r}")
        if attr == 'id':
            raise AttributeError("'Record' object attribute 'id' is read-only")
        self.write({attr: value})
