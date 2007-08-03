import copy
import itertools

import persistent
import BTrees
import zope.interface

import zc.relation.interfaces
import zc.relation.queryfactory
import zc.relation.catalog
import zc.relation.searchindex

##############################################################################
# common case search indexes

_marker = object()

class TransposingTransitive(persistent.Persistent):
    zope.interface.implements(zc.relation.interfaces.ISearchIndex)

    name = index = catalog = None

    def __init__(self, forward, reverse, static=(), names=()):
        # normalize
        if getattr(static, 'items', None) is not None:
            static = static.items()
        self.static = tuple(sorted(static))
        self.names = BTrees.family32.OO.Bucket([(nm, None) for nm in names])
        self.forward = forward
        self.reverse = reverse
        self.update = frozenset(
            itertools.chain((k for k, v in static), (forward, reverse)))
        match = list(static)
        match.append((forward, _marker))
        match.sort()
        self._match = tuple(match)
        match = list(static)
        match.append((reverse, _marker))
        match.sort()
        self._reverse_match = tuple(match)
        self.factory = zc.relation.queryfactory.TransposingTransitive(
            forward, reverse)

    def copy(self, catalog=None):
        new = self.__class__.__new__(self.__class__)
        new.names = BTrees.family32.OO.Bucket()
        for nm, val in self.names.items():
            if val is not None:
                new_val = zc.relation.catalog.getMapping(
                    self.catalog.getValueModuleTools(nm))()
                for k, v in val.items():
                    new_val[k] = copy.copy(v)
                val = new_val
            new.names[nm] = val
        new.forward = self.forward
        new.reverse = self.reverse
        new.factory = self.factory
        new.static = self.static
        new._match = self._match
        new._reverse_match = self._reverse_match
        if self.index is not None:
            if catalog is None:
                catalog = self.catalog
            new.catalog = catalog
            new.index = zc.relation.catalog.getMapping(
                self.catalog.getRelationModuleTools())()
            for k, v in self.index.items():
                new.index[k] = copy.copy(v)
        new.factory = self.factory
        return new

    def setCatalog(self, catalog):
        if catalog is None:
            self.index = self.catalog = None
            return
        elif self.catalog is not None:
            raise ValueError('catalog already set')
        self.catalog = catalog
        self.index = zc.relation.catalog.getMapping(
            self.catalog.getRelationModuleTools())()
        for nm in self.names.keys():
            self.names[nm] = zc.relation.catalog.getMapping(
                self.catalog.getValueModuleTools(nm))()
        for token in catalog.getRelationTokens():
            if token not in self.index:
                self._index(token)

    def _buildQuery(self, dynamic):
        res = BTrees.family32.OO.Bucket(self.static)
        res[dynamic] = None
        return res

    def _index(self, token, removals=None, remove=False):
        starts = set((token,))
        if removals and self.forward in removals:
            starts.update(t for t in removals[self.forward] if t is not None)
        tokens = set()
        reverseQuery = self._buildQuery(self.reverse)
        for token in starts:
            getQueries = self.factory(dict(reverseQuery), self.catalog)
            tokens.update(chain[-1] for chain in
                          self.catalog.yieldRelationTokenChains(
                            reverseQuery, ((token,),), None, None, None,
                            getQueries))
        if remove:
            tokens.remove(token)
            self.index.pop(token, None)
            for ix in self.names.values():
                ix.pop(token, None)
        # because of the possibilty of cycles involving this token in the
        # previous state, we first clean out all of the items "above"
        for token in tokens:
            self.index.pop(token, None)
        # now we go back and try to fill them back in again.  If there had
        # been a cycle, we can see now that we have to work down.
        relTools = self.catalog.getRelationModuleTools()
        query = self._buildQuery(self.forward)
        getQueries = self.factory(query, self.catalog)
        for token in tokens:
            if token in self.index: # must have filled it in during a cycle
                continue
            stack = [[token, None, set(), [], set((token,)), False]]
            while stack:
                token, child, sets, empty, traversed_tokens, cycled = stack[-1]
                if not sets:
                    rels = zc.relation.catalog.multiunion(
                        (self.catalog.getRelationTokens(q) for q in
                         getQueries([token])), relTools)
                    for rel in rels:
                        if rel == token:
                            # cycles on itself.
                            sets.add(relTools['Set']((token,)))
                            continue
                        indexed = self.index.get(rel)
                        if indexed is None:
                            iterator = reversed(stack)
                            traversed = [iterator.next()]
                            for info in iterator:
                                if rel == info[0]:
                                    sets = info[2]
                                    traversed_tokens = info[4]
                                    cycled = True
                                    for trav in traversed:
                                        sets.update(trav[2])
                                        trav[2] = sets
                                        traversed_tokens.update(trav[4])
                                        trav[4] = traversed_tokens
                                        trav[5] = True
                                    break
                                traversed.append(info)
                            else:
                                empty.append(rel)
                        else:
                            sets.add(indexed)
                    sets.add(rels)
                if child is not None:
                    sets.add(child)
                    # clear it out
                    child = stack[-1][1] = None
                if empty:
                    # We have one of two classes of situations.  Either this
                    # *is* currently a cycle, and the result for this and all
                    # children will be the same set; or this *may* be
                    # a cycle, because this is an initial indexing.
                    # Walk down, passing token.
                    next = empty.pop()
                    stack.append(
                        [next, None, set(), [], set((next,)), False])
                else:
                    stack.pop()
                    assert stack or not cycled, (
                        'top level should never consider itself cycled')
                    if not cycled:
                        rels = zc.relation.catalog.multiunion(
                            sets, relTools)
                        rels.insert(token)
                        names = {}
                        for nm in self.names.keys():
                            names[nm] = zc.relation.catalog.multiunion(
                                (self.catalog.getValueTokens(nm, rel)
                                 for rel in rels),
                                self.catalog.getValueModuleTools(nm))
                        for token in traversed_tokens:
                            self.index[token] = rels
                            for nm, ix in self.names.items():
                                ix[token] = names[nm]
                        if stack:
                            stack[-1][1] = rels

    # listener interface

    def relationAdded(self, token, catalog, additions):
        if token in self.index and not self.update.intersection(additions):
            return # no changes; don't do work
        self._index(token)

    def relationModified(self, token, catalog, additions, removals):
        if (token in self.index and not self.update.intersection(additions) and
            not self.update.intersection(removals)):
            return # no changes; don't do work
        self._index(token, removals)

    def relationRemoved(self, token, catalog, removals):
        self._index(token, removals, remove=True)

    def sourceCleared(self, catalog):
        if self.catalog is catalog:
            self.setCatalog(None)
            self.setCatalog(catalog)

    # end listener interface

    def getResults(self, name, query, maxDepth, filter, targetQuery,
                   targetFilter, queryFactory):
        if (queryFactory != self.factory or 
            name is not None and name not in self.names or
            maxDepth is not None or filter is not None or
            len(query) != len(self.static) + 1 or
            name is not None and (targetQuery or targetFilter is not None)):
            return None
        for given, match in itertools.izip(query.items(), self._match):
            if (given[0] != match[0] or 
                match[1] is not _marker and given[1] != match[1]):
                return None
        # TODO: try to use intransitive index, if available
        rels = self.catalog.getRelationTokens(query)
        if name is None:
            tools = self.catalog.getRelationModuleTools()
            ix = self.index
        else:
            tools = self.catalog.getValueModuleTools(name)
            ix = self.names[name]
        if rels is None:
            return tools['Set']()
        elif not rels:
            return rels
        res = zc.relation.catalog.multiunion(
            (ix.get(rel) for rel in rels), tools)
        if name is None:
            checkTargetFilter = zc.relation.catalog.makeCheckTargetFilter(
                targetQuery, targetFilter, self.catalog)
            if checkTargetFilter is not None:
                if not checkTargetFilter: # no results
                    res = tools['Set']()
                else:
                    res = tools['Set'](
                        rel for rel in res if checkTargetFilter([rel], query))
        return res


class Intransitive(persistent.Persistent):
    zope.interface.implements(
        zc.relation.interfaces.ISearchIndex,
        zc.relation.interfaces.IListener)

    index = catalog = name = queriesFactory = None
    update = frozenset()

    def __init__(self, names, name=None,
                 queriesFactory=None, getValueTokens=None, update=None):
        self.names = tuple(sorted(names))
        self.name = name
        self.queriesFactory = queriesFactory
        if update is None:
            update = names
            if name is not None:
                update += (name,)
        self.update = frozenset(update)
        self.getValueTokens = getValueTokens


    def copy(self, catalog=None):
        res = self.__class__.__new__(self.__class__)
        if self.index is not None:
            if catalog is None:
                catalog = self.catalog
            res.catalog = catalog
            res.index = BTrees.family32.OO.BTree()
            for k, v in self.index.items():
                res.index[k] = copy.copy(v)
        res.names = self.names
        res.name = self.name
        res.queriesFactory = self.queriesFactory
        res.update = self.update
        res.getValueTokens = self.getValueTokens
        return res

    def setCatalog(self, catalog):
        if catalog is None:
            self.index = self.catalog = None
            return
        elif self.catalog is not None:
            raise ValueError('catalog already set')
        self.catalog = catalog
        self.index = BTrees.family32.OO.BTree()
        self.sourceAdded(catalog)

    def relationAdded(self, token, catalog, additions):
        self._index(token, catalog, additions)

    def relationModified(self, token, catalog, additions, removals):
        self._index(token, catalog, additions, removals)

    def relationRemoved(self, token, catalog, removals):
        self._index(token, catalog, removals=removals, removed=True)

    def _index(self, token, catalog, additions=None, removals=None,
               removed=False):
        if ((not additions or not self.update.intersection(additions)) and
            (not removals or not self.update.intersection(removals))):
            return
        if additions is None:
            additions = {}
        if removals is None:
            removals = {}
        for query in self.getQueries(token, catalog, additions, removals,
                                     removed):
            self._indexQuery(tuple(query.items()))

    def _indexQuery(self, query):
            dquery = dict(query)
            if self.queriesFactory is not None:
                getQueries = self.queriesFactory(dquery, self.catalog)
            else:
                getQueries = lambda empty: (query,)
            res = zc.relation.catalog.multiunion(
                (self.catalog.getRelationTokens(q) for q in getQueries(())),
                self.catalog.getRelationModuleTools())
            if not res:
                self.index.pop(query, None)
            else:
                if self.name is not None:
                    res = zc.relation.catalog.multiunion(
                        (self.catalog.getValueTokens(self.name, r)
                         for r in res),
                        self.catalog.getValueModuleTools(self.name))
                self.index[query] = res

    def sourceAdded(self, catalog):
        queries = set()
        for token in catalog.getRelationTokens():
            additions = dict(
                (info['name'], catalog.getValueTokens(info['name'], token))
                for info in catalog.iterValueIndexInfo())
            queries.update(
                tuple(q.items()) for q in
                self.getQueries(token, catalog, additions, {}, False))
        for q in queries:
            self._indexQuery(q)

    def sourceRemoved(self, catalog):
        # this only really makes sense if the getQueries/getValueTokens was
        # changed
        queries = set()
        for token in catalog.getRelationTokens():
            removals = dict(
                (info['name'], catalog.getValueTokens(info['name'], token))
                for info in catalog.iterValueIndexInfo())
            queries.update(
                tuple(q.items()) for q in
                self.getQueries(token, catalog, {}, removals, True))
        for q in queries:
            self._indexQuery(q)

    def sourceCleared(self, catalog):
        if self.catalog is catalog:
            self.setCatalog(None)
            self.setCatalog(catalog)

    def getQueries(self, token, catalog, additions, removals, removed):
        source = {}
        for name in self.names:
            values = set()
            for changes in (additions, removals):
                value = changes.get(name, _marker)
                if value is None:
                    values.add(value)
                elif value is not _marker:
                    values.update(value)
            if values:
                if not removed and source:
                    source.clear()
                    break
                source[name] = values
        if removed and not source:
            return
        for name in self.names:
            res = None
            if self.getValueTokens is not None:
                res = self.getValueTokens(self, name, token, catalog, source,
                                          additions, removals, removed)
            if res is None:
                if name in source:
                    continue
                res = set((None,))
                current = self.catalog.getValueTokens(name, token)
                if current:
                    res.update(current)
            source[name] = res
        vals = []
        for name in self.names:
            src = source[name]
            iterator = iter(src)
            value = iterator.next() # should always have at least one
            vals.append([name, value, iterator, src])
        while 1:
            yield BTrees.family32.OO.Bucket(
                [(name, value) for name, value, iterator, src in vals])
            for s in vals:
                name, value, iterator, src = s
                try:
                    s[1] = iterator.next()
                except StopIteration:
                    iterator = s[2] = iter(src)
                    s[1] = iterator.next()
                else:
                    break
            else:
                break

    def getResults(self, name, query, maxDepth, filter, targetQuery,
                   targetFilter, queriesFactory):
        if (name != self.name or maxDepth not in (1, None) or
            queriesFactory != self.queriesFactory or targetQuery
            or filter is not None or targetFilter is not None):
            return # TODO could maybe handle some later
        names = []
        query = tuple(query.items())
        for nm, v in query:
            if isinstance(v, zc.relation.catalog.Any):
                return None # TODO open up
            names.append(nm)
        res = self.index.get(query)
        if res is None and self.names == tuple(names):
            if self.name is None:
                res = self.catalog.getRelationModuleTools()['Set']()
            else:
                res = self.catalog.getValueModuleTools(self.name)['Set']()
        return res
