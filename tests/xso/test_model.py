########################################################################
# File name: test_model.py
# This file is part of: aioxmpp
#
# LICENSE
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program.  If not, see
# <http://www.gnu.org/licenses/>.
#
########################################################################
import abc
import collections
import collections.abc
import contextlib
import copy
import enum
import functools
import unittest
import unittest.mock

import lxml.sax

import multidict

import aioxmpp.structs as structs
import aioxmpp.xso as xso
import aioxmpp.xso.model as xso_model
import aioxmpp.xso.types as xso_types
import aioxmpp.xso.query as xso_query

from aioxmpp.utils import etree, namespaces

from aioxmpp.xmltestutils import XMLTestCase


def from_wrapper(fun, *args, ctx=None):
    ev_type, *ev_args = yield
    return (yield from fun(*args+(ev_args, ctx)))


def contextless_from_wrapper(fun, *args):
    ev_type, *ev_args = yield
    return (yield from fun(*args+(ev_args,)))


def drive_from_events(method, instance, subtree, ctx):
    sd = xso.SAXDriver(
        functools.partial(from_wrapper, method, instance, ctx=ctx)
    )
    lxml.sax.saxify(subtree, sd)


def make_instance_mock(mapping={}):
    instance = unittest.mock.MagicMock()
    instance.TAG = ("uri:mock", "mock-instance")
    instance._xso_contents = dict(mapping)
    return instance


def unparse_to_node(xso, parent):
    handler = lxml.sax.ElementTreeContentHandler(
        makeelement=parent.makeelement)
    handler.startDocument()
    handler.startElementNS((None, "root"), None)
    xso.xso_serialise_to_sax(handler)
    handler.endElementNS((None, "root"), None)
    handler.endDocument()

    parent.extend(handler.etree.getroot())


class TestXMLStreamClass(unittest.TestCase):
    def setUp(self):
        self.ctx = xso_model.Context()

    def test_is_abc_meta(self):
        self.assertTrue(issubclass(xso_model.XMLStreamClass, abc.ABCMeta))

    def test_is_xso_query_class(self):
        self.assertTrue(issubclass(
            xso_model.XMLStreamClass,
            xso_query.Class,
        ))

    def test_init(self):
        class Cls(metaclass=xso_model.XMLStreamClass):
            TAG = None, "foo"

        self.assertIsNone(Cls.TEXT_PROPERTY)
        self.assertIsNone(Cls.COLLECTOR_PROPERTY)
        self.assertFalse(Cls.CHILD_MAP)
        self.assertFalse(Cls.CHILD_PROPS)
        self.assertFalse(Cls.ATTR_MAP)
        self.assertSequenceEqual(Cls.__slots__, ())

    def test_init_inherited(self):
        class Base(metaclass=xso_model.XMLStreamClass):
            pass

        class Child(Base):
            pass

        self.assertSequenceEqual(Child.__slots__, ())

    def test_init_takes_existing_slots(self):
        class Base(metaclass=xso_model.XMLStreamClass):
            __slots__ = ("_xso_contents",)

        self.assertSequenceEqual(Base.__slots__, ("_xso_contents",))

        class Child(Base):
            pass

        self.assertSequenceEqual(Child.__slots__, ())

    def test_init_unprotected(self):
        class Cls(metaclass=xso_model.XMLStreamClass, protect=False):
            pass

        self.assertFalse(hasattr(Cls, "__slots__"))

    def test_forbid_malformed_tag(self):
        with self.assertRaisesRegex(TypeError,
                                    "TAG attribute has incorrect format"):
            class ClsA(metaclass=xso_model.XMLStreamClass):
                TAG = "foo", "bar", "baz"

        with self.assertRaisesRegex(TypeError,
                                    "TAG attribute has incorrect format"):
            class ClsB(metaclass=xso_model.XMLStreamClass):
                TAG = "foo",

    def test_normalize_tag(self):
        class Cls(metaclass=xso_model.XMLStreamClass):
            TAG = "foo"
        self.assertEqual(
            (None, "foo"),
            Cls.TAG)

    def test_collect_text_property(self):
        class Cls(metaclass=xso_model.XMLStreamClass):
            TAG = "foo"
            prop = xso.Text()

        self.assertIs(
            Cls.prop.xq_descriptor,
            Cls.TEXT_PROPERTY.xq_descriptor
        )

    def test_inheritance_text_one_level(self):
        class ClsA(metaclass=xso_model.XMLStreamClass):
            text = xso.Text()

        with self.assertRaises(TypeError):
            class ClsFoo(ClsA):
                text2 = xso.Text()

        class ClsB(ClsA):
            pass

        self.assertIs(
            ClsA.text.xq_descriptor,
            ClsB.TEXT_PROPERTY.xq_descriptor
        )

    def test_multi_inheritance_text(self):
        class ClsA(metaclass=xso_model.XMLStreamClass):
            text = xso.Text()

        class ClsB(metaclass=xso_model.XMLStreamClass):
            text2 = xso.Text()

        with self.assertRaises(TypeError):
            class ClsC(ClsA, ClsB):
                pass

    def test_diamond_inheritance_text(self):
        class ClsA(metaclass=xso_model.XMLStreamClass):
            text = xso.Text()

        class ClsB(ClsA):
            pass

        class ClsC(ClsA):
            pass

        class ClsD(ClsB, ClsC):
            pass

        self.assertIs(
            ClsA.text.xq_descriptor,
            ClsD.TEXT_PROPERTY.xq_descriptor
        )

    def test_collect_child_text_property(self):
        class ClsA(metaclass=xso_model.XMLStreamClass):
            body = xso.ChildText("body")

        self.assertDictEqual(
            {
                (None, "body"): ClsA.body.xq_descriptor,
            },
            ClsA.CHILD_MAP
        )

        self.assertSetEqual(
            {ClsA.body.xq_descriptor},
            set(ClsA.CHILD_PROPS)
        )

    def test_collect_child_property(self):
        class ClsA(metaclass=xso_model.XMLStreamClass):
            TAG = "foo"

        class ClsB(metaclass=xso_model.XMLStreamClass):
            TAG = "bar"

        class ClsC(metaclass=xso_model.XMLStreamClass):
            TAG = "baz"

        class Cls(metaclass=xso_model.XMLStreamClass):
            c1 = xso.Child([ClsA, ClsB])
            c2 = xso.Child([ClsC])

        self.assertDictEqual(
            {
                ClsA.TAG: Cls.c1.xq_descriptor,
                ClsB.TAG: Cls.c1.xq_descriptor,
                ClsC.TAG: Cls.c2.xq_descriptor,
            },
            Cls.CHILD_MAP
        )
        self.assertSetEqual(
            {Cls.c1.xq_descriptor, Cls.c2.xq_descriptor},
            set(Cls.CHILD_PROPS)
        )

    def test_collect_child_flag_property(self):
        class Cls(metaclass=xso_model.XMLStreamClass):
            c1 = xso.ChildFlag(("uri:foo", "bar"))

        self.assertDictEqual(
            {
                ("uri:foo", "bar"): Cls.c1.xq_descriptor
            },
            Cls.CHILD_MAP
        )
        self.assertSetEqual(
            {Cls.c1.xq_descriptor},
            set(Cls.CHILD_PROPS)
        )

    def test_forbid_ambiguous_children(self):
        class ClsA(metaclass=xso_model.XMLStreamClass):
            TAG = "foo"

        class ClsB(metaclass=xso_model.XMLStreamClass):
            TAG = "foo"

        with self.assertRaisesRegex(TypeError, "ambiguous Child properties"):
            class Cls(metaclass=xso_model.XMLStreamClass):
                c1 = xso.Child([ClsA])
                c2 = xso.Child([ClsB])

    def test_inheritance_child(self):
        class ClsLeafA:
            TAG = "foo"

        class ClsLeafB:
            TAG = "bar"

        class ClsA(metaclass=xso_model.XMLStreamClass):
            c1 = xso.Child([ClsLeafA])

        class ClsB(ClsA):
            c2 = xso.Child([ClsLeafB])

        self.assertDictEqual(
            {
                "foo": ClsA.c1.xq_descriptor,
                "bar": ClsB.c2.xq_descriptor,
            },
            ClsB.CHILD_MAP)
        self.assertSetEqual(
            {ClsA.c1.xq_descriptor, ClsB.c2.xq_descriptor},
            set(ClsB.CHILD_PROPS)
        )

    def test_inheritance_child_ambiguous(self):
        class ClsLeafA:
            TAG = "foo"

        class ClsA(metaclass=xso_model.XMLStreamClass):
            c1 = xso.Child([ClsLeafA])

        with self.assertRaisesRegex(TypeError, "ambiguous Child properties"):
            class ClsB(ClsA):
                c2 = xso.Child([ClsLeafA])

    def test_multi_inheritance_child(self):
        class ClsLeafA:
            TAG = "foo"

        class ClsLeafB:
            TAG = "bar"

        class Base(metaclass=xso_model.XMLStreamClass):
            pass

        class ClsA(Base):
            c1 = xso.Child([ClsLeafA])

        class ClsB(Base):
            c2 = xso.Child([ClsLeafB])

        class ClsC(ClsA, ClsB):
            pass

        self.assertDictEqual(
            {
                "foo": ClsA.c1.xq_descriptor,
                "bar": ClsB.c2.xq_descriptor,
            },
            ClsC.CHILD_MAP
        )
        self.assertSetEqual(
            {ClsA.c1.xq_descriptor, ClsB.c2.xq_descriptor},
            set(ClsC.CHILD_PROPS)
        )

    def test_multi_inheritance_child_ambiguous(self):
        class ClsLeafA:
            TAG = "foo"

        class ClsA(metaclass=xso_model.XMLStreamClass):
            c1 = xso.Child([ClsLeafA])

        class ClsB(metaclass=xso_model.XMLStreamClass):
            c2 = xso.Child([ClsLeafA])

        with self.assertRaises(TypeError):
            class ClsC(ClsB, ClsA):
                pass

    def test_diamond_inheritance_child(self):
        class ClsLeafA:
            TAG = "foo"

        class ClsA(metaclass=xso_model.XMLStreamClass):
            c1 = xso.Child([ClsLeafA])

        class ClsB(ClsA):
            pass

        class ClsC(ClsA):
            pass

        class ClsD(ClsB, ClsC):
            pass

        self.assertDictEqual(
            {
                "foo": ClsA.c1.xq_descriptor,
            },
            ClsD.CHILD_MAP)
        self.assertSetEqual(
            {ClsA.c1.xq_descriptor},
            set(ClsD.CHILD_PROPS)
        )

    def test_collect_attr_property(self):
        class Cls(metaclass=xso_model.XMLStreamClass):
            attr1 = xso.Attr("foo")
            attr2 = xso.Attr("bar")
            attr3 = xso.Attr("baz")

        self.assertDictEqual(
            {
                (None, "foo"): Cls.attr1.xq_descriptor,
                (None, "bar"): Cls.attr2.xq_descriptor,
                (None, "baz"): Cls.attr3.xq_descriptor,
            },
            Cls.ATTR_MAP
        )

    def test_forbid_ambiguous_attr(self):
        with self.assertRaises(TypeError):
            class Cls(metaclass=xso_model.XMLStreamClass):
                attr1 = xso.Attr("foo")
                attr2 = xso.Attr("foo")

    def test_inheritance_attr(self):
        class ClsA(metaclass=xso_model.XMLStreamClass):
            attr1 = xso.Attr("foo")

        class ClsB(ClsA):
            attr2 = xso.Attr("bar")

        self.assertDictEqual(
            {
                (None, "foo"): ClsA.attr1.xq_descriptor,
                (None, "bar"): ClsB.attr2.xq_descriptor,
            },
            ClsB.ATTR_MAP)

    def test_inheritance_attr_ambiguous(self):
        class ClsA(metaclass=xso_model.XMLStreamClass):
            attr1 = xso.Attr("foo")

        with self.assertRaises(TypeError):
            class ClsB(ClsA):
                attr2 = xso.Attr("foo")

    def test_multi_inheritance_attr(self):
        class Base(metaclass=xso_model.XMLStreamClass):
            pass

        class ClsA(Base):
            attr1 = xso.Attr("foo")

        class ClsB(Base):
            attr2 = xso.Attr("bar")

        class ClsC(ClsB, ClsA):
            attr3 = xso.Attr("baz")

        self.assertDictEqual(
            {
                (None, "foo"): ClsA.attr1.xq_descriptor,
                (None, "bar"): ClsB.attr2.xq_descriptor,
                (None, "baz"): ClsC.attr3.xq_descriptor,
            },
            ClsC.ATTR_MAP
        )

    def test_multi_inheritance_attr_ambiguous(self):
        class ClsA(metaclass=xso_model.XMLStreamClass):
            attr1 = xso.Attr("foo")

        class ClsB(metaclass=xso_model.XMLStreamClass):
            attr2 = xso.Attr("foo")

        with self.assertRaises(TypeError):
            class ClsC(ClsB, ClsA):
                attr3 = xso.Attr("baz")

    def test_diamond_inheritance_attr(self):
        class ClsA(metaclass=xso_model.XMLStreamClass):
            attr = xso.Attr("foo")

        class ClsB(ClsA):
            pass

        class ClsC(ClsA):
            pass

        class ClsD(ClsB, ClsC):
            pass

        self.assertDictEqual(
            {
                (None, "foo"): ClsA.attr.xq_descriptor,
            },
            ClsD.ATTR_MAP
        )

    def test_collect_collector_property(self):
        class Cls(metaclass=xso_model.XMLStreamClass):
            prop = xso.Collector()

        self.assertIs(
            Cls.prop.xq_descriptor,
            Cls.COLLECTOR_PROPERTY.xq_descriptor
        )

    def test_forbid_duplicate_collector_property(self):
        with self.assertRaises(TypeError):
            class Cls(metaclass=xso_model.XMLStreamClass):
                propa = xso.Collector()
                propb = xso.Collector()

    def test_inheritance_collector_one_level(self):
        class ClsA(metaclass=xso_model.XMLStreamClass):
            text = xso.Collector()

        with self.assertRaises(TypeError):
            class ClsFoo(ClsA):
                text2 = xso.Collector()

        class ClsB(ClsA):
            pass

        self.assertIs(
            ClsB.COLLECTOR_PROPERTY.xq_descriptor,
            ClsA.text.xq_descriptor
        )

    def test_multi_inheritance_collector(self):
        class ClsA(metaclass=xso_model.XMLStreamClass):
            text = xso.Collector()

        class ClsB(metaclass=xso_model.XMLStreamClass):
            text2 = xso.Collector()

        with self.assertRaises(TypeError):
            class ClsC(ClsA, ClsB):
                pass

    def test_diamond_inheritance_collector(self):
        class ClsA(metaclass=xso_model.XMLStreamClass):
            text = xso.Collector()

        class ClsB(ClsA):
            pass

        class ClsC(ClsA):
            pass

        class ClsD(ClsB, ClsC):
            pass

        self.assertIs(ClsD.COLLECTOR_PROPERTY.xq_descriptor,
                      ClsA.text.xq_descriptor)

    def test_forbid_duplicate_text_property(self):
        with self.assertRaises(TypeError):
            class Cls(metaclass=xso_model.XMLStreamClass):
                TAG = "foo"
                propa = xso.Text()
                propb = xso.Text()

    def test_collect_child_list_property(self):
        class ClsA(metaclass=xso_model.XMLStreamClass):
            TAG = "foo"

        class ClsB(metaclass=xso_model.XMLStreamClass):
            TAG = "bar"

        class ClsC(metaclass=xso_model.XMLStreamClass):
            TAG = "baz"

        class Cls(metaclass=xso_model.XMLStreamClass):
            cl1 = xso.ChildList([ClsA, ClsB])
            cl2 = xso.ChildList([ClsC])

        self.assertDictEqual(
            {
                ClsA.TAG: Cls.cl1.xq_descriptor,
                ClsB.TAG: Cls.cl1.xq_descriptor,
                ClsC.TAG: Cls.cl2.xq_descriptor,
            },
            Cls.CHILD_MAP
        )
        self.assertSetEqual(
            {Cls.cl1.xq_descriptor, Cls.cl2.xq_descriptor},
            set(Cls.CHILD_PROPS)
        )

    def test_forbid_ambiguous_children_with_lists(self):
        class ClsA(metaclass=xso_model.XMLStreamClass):
            TAG = "foo"

        class ClsB(metaclass=xso_model.XMLStreamClass):
            TAG = "foo"

        with self.assertRaisesRegex(TypeError, "ambiguous Child properties"):
            class Cls(metaclass=xso_model.XMLStreamClass):
                c1 = xso.ChildList([ClsA])
                c2 = xso.Child([ClsB])

    def test_collect_child_tag_property(self):
        class Cls(metaclass=xso_model.XMLStreamClass):
            ct = xso.ChildTag(
                tags=[
                    "foo",
                    "bar"
                ],
                default_ns="uri:foo")

        self.assertDictEqual(
            {
                ("uri:foo", "foo"): Cls.ct.xq_descriptor,
                ("uri:foo", "bar"): Cls.ct.xq_descriptor,
            },
            Cls.CHILD_MAP
        )
        self.assertSetEqual(
            {Cls.ct.xq_descriptor},
            set(Cls.CHILD_PROPS)
        )

    def test_ordered_child_props(self):
        class Cls(metaclass=xso_model.XMLStreamClass):
            c1 = xso.ChildText((None, "a"))
            c2 = xso.ChildText((None, "b"))
            c3 = xso.ChildText((None, "c"))

        self.assertSequenceEqual(
            [
                Cls.c1.xq_descriptor,
                Cls.c2.xq_descriptor,
                Cls.c3.xq_descriptor,
            ],
            Cls.CHILD_PROPS
        )

    def test_register_child(self):
        class Cls(metaclass=xso_model.XMLStreamClass):
            TAG = "foo"

            child = xso.Child([])

        class ClsA(metaclass=xso_model.XMLStreamClass):
            TAG = "bar"

        class ClsB(metaclass=xso_model.XMLStreamClass):
            TAG = "baz"

        class ClsC(metaclass=xso_model.XMLStreamClass):
            TAG = "bar"

        Cls.register_child(Cls.child, ClsA)
        self.assertDictEqual(
            {
                (None, "bar"): Cls.child.xq_descriptor
            },
            Cls.CHILD_MAP
        )

        Cls.register_child(Cls.child, ClsB)
        self.assertDictEqual(
            {
                (None, "bar"): Cls.child.xq_descriptor,
                (None, "baz"): Cls.child.xq_descriptor,
            },
            Cls.CHILD_MAP
        )

        with self.assertRaises(ValueError):
            Cls.register_child(Cls.child, ClsC)

    def test_register_child_rejects_update_of_class_with_descendants(self):
        class Cls(metaclass=xso_model.XMLStreamClass):
            TAG = "foo"

            child = xso.Child([])

        class ClsA(Cls):
            TAG = "bar"

        class ClsB(metaclass=xso_model.XMLStreamClass):
            TAG = "baz"

        with self.assertRaisesRegex(
                TypeError,
                "register_child is forbidden on classes with subclasses"):
            Cls.register_child(Cls.child, ClsB)

    def test_call_error_handler_on_broken_child(self):
        class Bar(xso.XSO):
            TAG = "bar"

            text = xso.Text(
                type_=xso.Integer()
            )

        class Cls(metaclass=xso_model.XMLStreamClass):
            TAG = "foo"

            child = xso.Child([Bar])

        Cls.xso_error_handler = unittest.mock.MagicMock()
        Cls.xso_error_handler.return_value = False

        gen = Cls.parse_events((None, "foo", {}), self.ctx)
        next(gen)
        gen.send(("start", None, "bar", {}))
        gen.send(("text", "foobar"))
        with self.assertRaises(ValueError):
            gen.send(("end", ))

        self.assertSequenceEqual(
            [
                unittest.mock.call(
                    Cls.child.xq_descriptor,
                    [None, "bar", {}],
                    unittest.mock.ANY)
            ],
            Cls.xso_error_handler.mock_calls
        )

    def test_error_handler_on_broken_child_can_suppress(self):
        class Bar(xso.XSO):
            TAG = "bar"

            text = xso.Text(
                type_=xso.Integer()
            )

        class Cls(xso.XSO):
            TAG = "foo"

            child = xso.Child([Bar])

        Cls.xso_error_handler = unittest.mock.MagicMock()
        Cls.xso_error_handler.return_value = True

        gen = Cls.parse_events((None, "foo", {}), self.ctx)
        next(gen)
        gen.send(("start", None, "bar", {}))
        gen.send(("text", "foobar"))
        gen.send(("end",))
        gen.send(("start", None, "bar", {}))
        gen.send(("text", "123"))
        gen.send(("end",))
        with self.assertRaises(StopIteration) as ctx:
            gen.send(("end",))

        self.assertSequenceEqual(
            [
                unittest.mock.call(
                    Cls.child.xq_descriptor,
                    [None, "bar", {}],
                    unittest.mock.ANY)
            ],
            Cls.xso_error_handler.mock_calls
        )

    def test_call_error_handler_on_unexpected_child(self):
        class Bar(xso.XSO):
            TAG = "bar"

            text = xso.Text(
                type_=xso.Integer()
            )

        class Cls(metaclass=xso_model.XMLStreamClass):
            TAG = "foo"
            UNKNOWN_CHILD_POLICY = xso.UnknownChildPolicy.FAIL

            child = xso.Child([Bar])

        Cls.xso_error_handler = unittest.mock.MagicMock()
        Cls.xso_error_handler.return_value = False

        gen = Cls.parse_events((None, "foo", {}), self.ctx)
        next(gen)
        with self.assertRaises(ValueError):
            gen.send(("start", None, "baz", {}))

        self.assertSequenceEqual(
            [
                unittest.mock.call(
                    None,
                    [None, "baz", {}],
                    None)
            ],
            Cls.xso_error_handler.mock_calls
        )

    def test_error_handler_on_unexpected_child_can_suppress(self):
        class Bar(xso.XSO):
            TAG = "bar"

            text = xso.Text(
                type_=xso.Integer()
            )

        class Cls(xso.XSO):
            TAG = "foo"
            UNKNOWN_CHILD_POLICY = xso.UnknownChildPolicy.FAIL

            child = xso.Child([Bar])

        Cls.xso_error_handler = unittest.mock.MagicMock()
        Cls.xso_error_handler.return_value = True

        gen = Cls.parse_events((None, "foo", {}), self.ctx)
        next(gen)
        gen.send(("start", None, "baz", {}))
        gen.send(("text", "foo"))
        gen.send(("start", None, "bar", {}))
        gen.send(("end",))
        gen.send(("end",))
        gen.send(("start", None, "bar", {}))
        gen.send(("text", "123"))
        gen.send(("end",))
        with self.assertRaises(StopIteration) as ctx:
            gen.send(("end",))

        self.assertSequenceEqual(
            [
                unittest.mock.call(
                    None,
                    [None, "baz", {}],
                    None)
            ],
            Cls.xso_error_handler.mock_calls
        )

        self.assertIsInstance(
            ctx.exception.value,
            Cls
        )

        self.assertIsInstance(
            ctx.exception.value.child,
            Bar
        )

        self.assertEqual(
            123,
            ctx.exception.value.child.text
        )

    def test_call_error_handler_on_broken_text(self):
        class Cls(metaclass=xso_model.XMLStreamClass):
            TAG = "foo"

            text = xso.Text(
                type_=xso.Integer()
            )

        Cls.xso_error_handler = unittest.mock.MagicMock()
        Cls.xso_error_handler.return_value = False

        gen = Cls.parse_events((None, "foo", {}), self.ctx)
        next(gen)
        gen.send(("text", "foo"))
        gen.send(("text", "bar"))
        with self.assertRaises(ValueError):
            gen.send(("end",))

        self.assertSequenceEqual(
            [
                unittest.mock.call(
                    Cls.text.xq_descriptor,
                    "foobar",
                    unittest.mock.ANY)
            ],
            Cls.xso_error_handler.mock_calls
        )

    def test_ignore_parse_error_with_erroneous_as_absent_text(self):
        class Cls(xso.XSO):
            TAG = "foo"

            text = xso.Text(
                type_=xso.Integer(),
                erroneous_as_absent=True,
                default=-1,
            )

        Cls.xso_error_handler = unittest.mock.MagicMock()
        Cls.xso_error_handler.return_value = False

        gen = Cls.parse_events((None, "foo", {}), self.ctx)
        next(gen)
        gen.send(("text", "foo"))
        gen.send(("text", "bar"))
        with self.assertRaises(StopIteration) as ctx:
            gen.send(("end",))

        obj = ctx.exception.value

        self.assertSequenceEqual(
            [],
            Cls.xso_error_handler.mock_calls
        )

        self.assertEqual(obj.text, -1)

    def test_error_handler_on_broken_text_can_suppress(self):
        class Cls(xso.XSO):
            TAG = "foo"

            text = xso.Text(
                type_=xso.Integer()
            )

        Cls.xso_error_handler = unittest.mock.MagicMock()
        Cls.xso_error_handler.return_value = True

        gen = Cls.parse_events((None, "foo", {}), self.ctx)
        next(gen)
        gen.send(("text", "foo"))
        gen.send(("text", "bar"))
        with self.assertRaises(StopIteration) as ctx:
            gen.send(("end",))

        self.assertSequenceEqual(
            [
                unittest.mock.call(
                    Cls.text.xq_descriptor,
                    "foobar",
                    unittest.mock.ANY)
            ],
            Cls.xso_error_handler.mock_calls
        )

        self.assertIsInstance(
            ctx.exception.value,
            Cls
        )

    def test_call_error_handler_on_unexpected_text(self):
        class Cls(metaclass=xso_model.XMLStreamClass):
            TAG = "foo"

        Cls.xso_error_handler = unittest.mock.MagicMock()
        Cls.xso_error_handler.return_value = False

        gen = Cls.parse_events((None, "foo", {}), self.ctx)
        next(gen)
        with self.assertRaises(ValueError):
            gen.send(("text", "foo"))

        self.assertSequenceEqual(
            [
                unittest.mock.call(
                    None,
                    "foo",
                    None)
            ],
            Cls.xso_error_handler.mock_calls
        )

    def test_error_handler_on_unexpected_text_can_suppress(self):
        class Cls(xso.XSO):
            TAG = "foo"

        Cls.xso_error_handler = unittest.mock.MagicMock()
        Cls.xso_error_handler.return_value = True

        gen = Cls.parse_events((None, "foo", {}), self.ctx)
        next(gen)
        gen.send(("text", "foo"))
        gen.send(("text", "bar"))
        with self.assertRaises(StopIteration) as ctx:
            gen.send(("end",))

        self.assertSequenceEqual(
            [
                unittest.mock.call(
                    None,
                    "foo",
                    None),
                unittest.mock.call(
                    None,
                    "bar",
                    None),
            ],
            Cls.xso_error_handler.mock_calls
        )

        self.assertIsInstance(
            ctx.exception.value,
            Cls
        )

    def test_call_error_handler_on_broken_attr(self):
        class Cls(xso.XSO):
            TAG = "foo"

            attr = xso.Attr(
                tag=(None, "attr"),
                type_=xso.Integer()
            )

        Cls.xso_error_handler = unittest.mock.MagicMock()
        Cls.xso_error_handler.return_value = False

        gen = Cls.parse_events(
            (
                None,
                "foo", {
                    (None, "attr"): "foobar",
                }
            ),
            self.ctx)
        with self.assertRaises(ValueError):
            next(gen)

        self.assertSequenceEqual(
            [
                unittest.mock.call(
                    Cls.attr.xq_descriptor,
                    "foobar",
                    unittest.mock.ANY)
            ],
            Cls.xso_error_handler.mock_calls
        )

    def test_error_handler_on_broken_attr_can_suppress(self):
        class Cls(xso.XSO):
            TAG = "foo"

            attr = xso.Attr(
                tag=(None, "attr"),
                type_=xso.Integer()
            )

        Cls.xso_error_handler = unittest.mock.MagicMock()
        Cls.xso_error_handler.return_value = True

        gen = Cls.parse_events(
            (
                None,
                "foo", {
                    (None, "attr"): "foobar",
                }
            ),
            self.ctx)
        next(gen)

        self.assertSequenceEqual(
            [
                unittest.mock.call(
                    Cls.attr.xq_descriptor,
                    "foobar",
                    unittest.mock.ANY)
            ],
            Cls.xso_error_handler.mock_calls
        )

    def test_call_error_handler_on_missing_attr(self):
        class Cls(metaclass=xso_model.XMLStreamClass):
            TAG = "foo"

            attr = xso.Attr(
                tag=(None, "attr"),
            )

        Cls.xso_error_handler = unittest.mock.MagicMock()
        Cls.xso_error_handler.return_value = False

        gen = Cls.parse_events(
            (
                None,
                "foo", {
                }
            ),
            self.ctx)
        with self.assertRaises(ValueError):
            next(gen)

        self.assertSequenceEqual(
            [
                unittest.mock.call(
                    Cls.attr.xq_descriptor,
                    None,
                    unittest.mock.ANY)
            ],
            Cls.xso_error_handler.mock_calls
        )

    def test_error_handler_on_missing_attr_can_suppress(self):
        class Cls(metaclass=xso_model.XMLStreamClass):
            TAG = "foo"

            attr = xso.Attr(
                tag=(None, "attr"),
            )

        Cls.xso_error_handler = unittest.mock.MagicMock()
        Cls.xso_error_handler.return_value = True

        gen = Cls.parse_events(
            (
                None,
                "foo", {
                }
            ),
            self.ctx)
        next(gen)

        self.assertSequenceEqual(
            [
                unittest.mock.call(
                    Cls.attr.xq_descriptor,
                    None,
                    unittest.mock.ANY)
            ],
            Cls.xso_error_handler.mock_calls
        )

    def test_call_missing_on_missing_attr(self):
        missing = unittest.mock.MagicMock()
        missing.return_value = "123"

        ctx = unittest.mock.MagicMock()

        class Cls(xso.XSO):
            TAG = "foo"

            attr = xso.Attr(
                tag=(None, "attr"),
                missing=missing
            )

        gen = Cls.parse_events(
            (
                None,
                "foo", {
                }
            ),
            ctx)
        next(gen)
        with self.assertRaises(StopIteration) as exc:
            gen.send(("end", ))
        obj = exc.exception.value

        self.assertSequenceEqual(
            [
                unittest.mock.call(obj, ctx.__enter__())
            ],
            missing.mock_calls
        )

    def test_call_missing_on_erroneous_attr_with_erroneous_as_absent(self):
        missing = unittest.mock.MagicMock()
        missing.return_value = 123

        ctx = unittest.mock.MagicMock()

        class Cls(xso.XSO):
            TAG = "foo"

            attr = xso.Attr(
                tag=(None, "attr"),
                type_=xso.Integer(),
                erroneous_as_absent=True,
                missing=missing,
            )

        gen = Cls.parse_events(
            (
                None,
                "foo", {
                    (None, "attr"): "xyz",
                }
            ),
            ctx)
        next(gen)
        with self.assertRaises(StopIteration) as exc:
            gen.send(("end", ))
        obj = exc.exception.value

        self.assertSequenceEqual(
            [
                unittest.mock.call(obj, ctx.__enter__())
            ],
            missing.mock_calls
        )

    def test_mark_attributes_as_incomplete_in_attribute_error_handling(
            self):
        class Cls(xso.XSO):
            TAG = "foo"

            foo = xso.Attr("foo", type_=xso.Integer())
            bar = xso.Attr("bar")

        Cls.xso_error_handler = unittest.mock.MagicMock()
        Cls.xso_error_handler.return_value = True

        gen = Cls.parse_events((None, "foo", {(None, "foo"): "10x"}), self.ctx)
        next(gen)
        with self.assertRaises(StopIteration) as ctx:
            gen.send(("end", ))

        obj = ctx.exception.value

        with self.assertRaisesRegex(
                AttributeError,
                "attribute value is incomplete"):
            obj.foo

        with self.assertRaisesRegex(
                AttributeError,
                "attribute value is incomplete"):
            obj.bar

    def test_do_not_mark_parsed_attributes_as_incomplete(self):
        class Cls(xso.XSO):
            TAG = "foo"

            foo = xso.Attr("foo", type_=xso.Integer())
            bar = xso.Attr("bar")

        Cls.xso_error_handler = unittest.mock.MagicMock()
        Cls.xso_error_handler.return_value = True

        gen = Cls.parse_events((None, "foo", collections.OrderedDict([
            ((None, "bar"), "fnord"),
            ((None, "foo"), "x")
        ])), self.ctx)
        next(gen)
        with self.assertRaises(StopIteration) as ctx:
            gen.send(("end", ))

        obj = ctx.exception.value

        with self.assertRaisesRegex(
                AttributeError,
                "attribute value is incomplete"):
            obj.foo

        self.assertEqual(obj.bar, "fnord")

    def test_do_not_mark_attributes_as_incomplete_in_missing_attribute_handling(
            self):
        class Cls(xso.XSO):
            TAG = "foo"

            foo = xso.Attr("foo")
            bar = xso.Attr("bar")

        Cls.xso_error_handler = unittest.mock.MagicMock()
        Cls.xso_error_handler.return_value = True

        gen = Cls.parse_events((None, "foo", {}), self.ctx)
        next(gen)
        with self.assertRaises(StopIteration) as ctx:
            gen.send(("end", ))

        obj = ctx.exception.value

        with self.assertRaisesRegex(
                AttributeError,
                "attribute is unset"):
            obj.foo

        with self.assertRaisesRegex(
                AttributeError,
                "attribute is unset"):
            obj.bar

    def test_lang_propagation_from_context(self):
        class Bar(xso.XSO):
            TAG = "bar"

            lang = xso.Attr(
                tag=(namespaces.xml, "lang"),
                missing=xso.lang_attr
            )

        class Foo(xso.XSO):
            TAG = "foo"

            lang = xso.Attr(
                tag=(namespaces.xml, "lang"),
                missing=xso.lang_attr
            )

            child = xso.Child([Bar])

        ctx = xso_model.Context()
        ctx.lang = "de-DE"

        caught_obj = None
        def catch(obj):
            nonlocal caught_obj
            caught_obj = obj

        sd = xso.SAXDriver(
            functools.partial(from_wrapper,
                              Foo.parse_events,
                              ctx=ctx),
            on_emit=catch
        )
        lxml.sax.saxify(
            etree.fromstring(
                "<foo><bar xml:lang='en-GB'/></foo>"
            ),
            sd)

        self.assertIsNotNone(caught_obj)
        self.assertEqual(
            "de-DE",
            caught_obj.lang
        )
        self.assertEqual(
            "en-GB",
            caught_obj.child.lang
        )

    def test_lang_propagation_from_parent(self):
        class Bar(xso.XSO):
            TAG = "bar"

            lang = xso.Attr(
                tag=(namespaces.xml, "lang"),
                missing=xso.lang_attr
            )

        class Foo(xso.XSO):
            TAG = "foo"

            lang = xso.Attr(
                tag=(namespaces.xml, "lang"),
                missing=xso.lang_attr
            )

            child = xso.Child([Bar])

        ctx = xso_model.Context()

        caught_obj = None
        def catch(obj):
            nonlocal caught_obj
            caught_obj = obj

        sd = xso.SAXDriver(
            functools.partial(from_wrapper,
                              Foo.parse_events,
                              ctx=ctx),
            on_emit=catch
        )
        lxml.sax.saxify(
            etree.fromstring(
                "<foo xml:lang='en-GB'><bar/></foo>"
            ),
            sd)

        self.assertIsNotNone(caught_obj)
        self.assertEqual(
            "en-GB",
            caught_obj.lang
        )
        self.assertEqual(
            "en-GB",
            caught_obj.child.lang
        )

    def test_deep_lang_propagation_from_parent_with_confusion(self):
        class Baz(xso.XSO):
            TAG = "baz"

            lang = xso.Attr(
                tag=(namespaces.xml, "lang"),
                missing=xso.lang_attr
            )

        class Bar(xso.XSO):
            TAG = "bar"

            lang = xso.Attr(
                tag=(namespaces.xml, "lang"),
                default=None
            )

            child = xso.Child([Baz])

        class Foo(xso.XSO):
            TAG = "foo"

            lang = xso.Attr(
                tag=(namespaces.xml, "lang"),
                missing=xso.lang_attr
            )

            child = xso.Child([Bar])

        ctx = xso_model.Context()

        caught_obj = None
        def catch(obj):
            nonlocal caught_obj
            caught_obj = obj

        sd = xso.SAXDriver(
            functools.partial(from_wrapper,
                              Foo.parse_events,
                              ctx=ctx),
            on_emit=catch
        )
        lxml.sax.saxify(
            etree.fromstring(
                "<foo xml:lang='en-GB'><bar><baz/></bar></foo>"
            ),
            sd)

        self.assertIsNotNone(caught_obj)
        self.assertEqual(
            "en-GB",
            caught_obj.lang
        )
        self.assertIsNone(caught_obj.child.lang)
        self.assertEqual(
            "en-GB",
            caught_obj.child.child.lang
        )

    def test_validate_after_parse(self):
        class Foo(xso.XSO):
            TAG = "foo"

        ctx = xso_model.Context()

        catch = unittest.mock.Mock()
        sd = xso.SAXDriver(
            functools.partial(from_wrapper,
                              Foo.parse_events,
                              ctx=ctx),
            on_emit=catch)
        with unittest.mock.patch.object(Foo, "validate") as validate:
            lxml.sax.saxify(
                etree.fromstring(
                    "<foo />"
                ),
                sd
            )

        self.assertSequenceEqual(
            [
                unittest.mock.call(unittest.mock.ANY),
            ],
            catch.mock_calls
        )
        self.assertSequenceEqual(
            [
                unittest.mock.call(),
            ],
            validate.mock_calls
        )

    def test_setattr_refuses_to_overwrite_existing_descriptor(self):
        class Foo(metaclass=xso_model.XMLStreamClass):
            attr = xso.Attr("bar")

        with self.assertRaisesRegex(AttributeError,
                                    "cannot rebind XSO descriptors"):
            Foo.attr = xso.Attr("baz")

    def test_setattr_allows_to_overwrite_everything_else(self):
        class Foo(metaclass=xso_model.XMLStreamClass):
            def method(self):
                pass

            xyz = 123

        Foo.xyz = 345
        Foo.method = "bar"

    def test_setattr_Attr(self):
        class Foo(metaclass=xso_model.XMLStreamClass):
            pass

        Foo.attr = xso.Attr("bar")

        self.assertIn(
            (None, "bar"),
            Foo.ATTR_MAP
        )
        self.assertIs(
            Foo.ATTR_MAP[None, "bar"],
            Foo.attr.xq_descriptor
        )

    def test_setattr_Attr_rejects_ambiguous_tags(self):
        class Foo(metaclass=xso_model.XMLStreamClass):
            pass

        Foo.attr = xso.Attr("bar")

        with self.assertRaisesRegex(TypeError,
                                     "ambiguous Attr properties"):
            Foo.attr2 = xso.Attr("bar")

    def test_setattr_Child(self):
        class Foo(metaclass=xso_model.XMLStreamClass):
            pass

        class Bar(metaclass=xso_model.XMLStreamClass):
            TAG = (None, "foobar")

        Foo.child = xso.Child([Bar])

        self.assertIn(
            Foo.child.xq_descriptor,
            Foo.CHILD_PROPS
        )
        self.assertIn(
            (None, "foobar"),
            Foo.CHILD_MAP
        )
        self.assertIs(
            Foo.child.xq_descriptor,
            Foo.CHILD_MAP[None, "foobar"]
        )

    def test_setattr_Child_rejects_ambiguous_tags(self):
        class Foo(metaclass=xso_model.XMLStreamClass):
            pass

        class Bar(metaclass=xso_model.XMLStreamClass):
            TAG = (None, "foobar")

        class Baz(metaclass=xso_model.XMLStreamClass):
            TAG = (None, "foobar")

        Foo.child1 = xso.Child([Bar])

        with self.assertRaisesRegex(TypeError,
                                    "ambiguous Child properties"):
            Foo.child2 = xso.Child([Baz])

    def test_setattr_Child_rejects_atomically(self):
        class Foo(metaclass=xso_model.XMLStreamClass):
            pass

        class Bar(metaclass=xso_model.XMLStreamClass):
            TAG = (None, "foobar")

        class Baz(metaclass=xso_model.XMLStreamClass):
            TAG = (None, "foobar")

        class Fnord(metaclass=xso_model.XMLStreamClass):
            TAG = (None, "fnord")

        Foo.child1 = xso.Child([Bar])

        with self.assertRaisesRegex(TypeError,
                                    "ambiguous Child properties"):
            Foo.child2 = xso.Child([Fnord, Baz])

        self.assertNotIn(
            Fnord.TAG,
            Foo.CHILD_MAP
        )

    def test_setattr_ChildText(self):
        class Foo(metaclass=xso_model.XMLStreamClass):
            pass

        Foo.text = xso.ChildText(tag=(None, "foobar"))

        self.assertIn(
            (None, "foobar"),
            Foo.CHILD_MAP
        )
        self.assertIs(
            Foo.text.xq_descriptor,
            Foo.CHILD_MAP[None, "foobar"]
        )
        self.assertIn(
            Foo.text.xq_descriptor,
            Foo.CHILD_PROPS
        )

    def test_setattr_ChildText_rejects_ambiguous(self):
        class Bar(metaclass=xso_model.XMLStreamClass):
            TAG = (None, "foobar")

        class Foo(metaclass=xso_model.XMLStreamClass):
            child = xso.Child([Bar])

        with self.assertRaisesRegex(TypeError,
                                    "ambiguous Child properties"):
            Foo.text = xso.ChildText(tag=(None, "foobar"))

    def test_setattr_ChildTag(self):
        class Foo(metaclass=xso_model.XMLStreamClass):
            pass

        Foo.tag = xso.ChildTag(
            [
                (None, "foo"),
                (None, "bar"),
                (None, "baz"),
            ]
        )

        for tag in ["foo", "bar", "baz"]:
            self.assertIn(
                (None, tag),
                Foo.CHILD_MAP
            )
            self.assertIs(
                Foo.tag.xq_descriptor,
                Foo.CHILD_MAP[None, tag]
            )

        self.assertIn(
            Foo.tag.xq_descriptor,
            Foo.CHILD_PROPS
        )

    def test_setattr_ChildTag_rejects_ambiguous(self):
        class Bar(metaclass=xso_model.XMLStreamClass):
            TAG = (None, "bar")

        class Foo(metaclass=xso_model.XMLStreamClass):
            child = xso.Child([Bar])

        with self.assertRaisesRegex(TypeError,
                                     "ambiguous Child properties"):
            Foo.tag = xso.ChildTag(
                [
                    (None, "foo"),
                    (None, "bar"),
                    (None, "baz"),
                ]
            )

    def test_setattr_ChildTag_rejects_atomically(self):
        class Bar(metaclass=xso_model.XMLStreamClass):
            TAG = (None, "bar")

        class Foo(metaclass=xso_model.XMLStreamClass):
            child = xso.Child([Bar])

        with self.assertRaisesRegex(TypeError,
                                     "ambiguous Child properties"):
            Foo.tag = xso.ChildTag(
                [
                    (None, "foo"),
                    (None, "bar"),
                    (None, "baz"),
                ]
            )

        self.assertNotIn(
            (None, "foo"),
            Foo.CHILD_MAP
        )

        self.assertNotIn(
            (None, "baz"),
            Foo.CHILD_MAP
        )

    def test_setattr_Collector(self):
        class Foo(metaclass=xso_model.XMLStreamClass):
            pass

        Foo.collector = xso.Collector()

        self.assertIs(
            Foo.collector.xq_descriptor,
            Foo.COLLECTOR_PROPERTY.xq_descriptor
        )

    def test_setattr_Collector_rejects_duplicate(self):
        class Foo(metaclass=xso_model.XMLStreamClass):
            pass

        Foo.collector1 = xso.Collector()

        with self.assertRaisesRegex(TypeError,
                                     "multiple Collector properties"):
            Foo.collector2 = xso.Collector()

    def test_setattr_Text(self):
        class Foo(metaclass=xso_model.XMLStreamClass):
            pass

        Foo.text = xso.Text()

        self.assertIs(
            Foo.text.xq_descriptor,
            Foo.TEXT_PROPERTY.xq_descriptor
        )

    def test_setattr_Text_rejects_duplicate(self):
        class Foo(metaclass=xso_model.XMLStreamClass):
            pass

        Foo.text1 = xso.Text()

        with self.assertRaisesRegex(TypeError,
                                     "multiple Text properties"):
            Foo.text2 = xso.Text()

    def test_setattr_rejects_adding_properties_to_class_with_descendants(self):
        class Foo(metaclass=xso_model.XMLStreamClass):
            pass

        class Bar(Foo):
            pass

        msg_regexp = ("adding descriptors is forbidden on classes with"
                      " subclasses")

        with self.assertRaisesRegex(TypeError, msg_regexp):
            Foo.attr = xso.Attr("abc")

        with self.assertRaisesRegex(TypeError, msg_regexp):
            Foo.attr = xso.Child([])

        with self.assertRaisesRegex(TypeError, msg_regexp):
            Foo.attr = xso.ChildText((None, "abc"))

        with self.assertRaisesRegex(TypeError, msg_regexp):
            Foo.attr = xso.ChildTag([(None, "abc")])

        with self.assertRaisesRegex(TypeError, msg_regexp):
            Foo.attr = xso.Text()

        with self.assertRaisesRegex(TypeError, msg_regexp):
            Foo.attr = xso.Collector()

    def test_setattr_permits_adding_non_descriptors_to_class_with_descendants(self):
        class Foo(metaclass=xso_model.XMLStreamClass):
            pass

        class Bar(Foo):
            pass

        Foo.bar = 123
        Foo.baz = "fnord"

    def test_delattr_rejects_removal_of_descriptors(self):
        class Foo(metaclass=xso_model.XMLStreamClass):
            attr = xso.Attr("foo")

        Foo.text = xso.Text()

        msg_regexp = "cannot unbind XSO descriptors"

        with self.assertRaisesRegex(AttributeError, msg_regexp):
            del Foo.attr

        with self.assertRaisesRegex(AttributeError, msg_regexp):
            del Foo.text

    def test_delattr_removes_everything_else(self):
        class Foo(metaclass=xso_model.XMLStreamClass):
            foo = 123
            bar = "baz"

            def method(self):
                pass

        del Foo.foo
        del Foo.bar
        del Foo.method

        self.assertFalse(hasattr(
            Foo,
            "foo"
        ))

        self.assertFalse(hasattr(
            Foo,
            "bar"
        ))

        self.assertFalse(hasattr(
            Foo,
            "method"
        ))

    def test_setattr_ChildFlag(self):
        class Foo(metaclass=xso_model.XMLStreamClass):
            pass

        Foo.child = xso.ChildFlag(("urn:test", "test"))

        self.assertIn(
            Foo.child.xq_descriptor,
            Foo.CHILD_PROPS
        )
        self.assertIn(
            ("urn:test", "test"),
            Foo.CHILD_MAP
        )
        self.assertIs(
            Foo.child.xq_descriptor,
            Foo.CHILD_MAP["urn:test", "test"]
        )

    def test_setattr_ChildFlag_rejects_ambiguous(self):
        class Bar(metaclass=xso_model.XMLStreamClass):
            TAG = (None, "bar")

        class Foo(metaclass=xso_model.XMLStreamClass):
            child = xso.Child([Bar])

        with self.assertRaisesRegex(TypeError,
                                    "ambiguous Child properties"):
            Foo.tag = xso.ChildFlag(
                (None, "bar")
            )

    def test_parse_events_does_not_call_init_but_validate_and_new(self):
        class Cls(metaclass=xso_model.XMLStreamClass):
            TAG = "foo"

            def validate(self):
                pass

            def xso_after_load(self):
                pass

        instance = unittest.mock.Mock(spec=Cls())

        with contextlib.ExitStack() as stack:
            init = stack.enter_context(
                unittest.mock.patch.object(type(Cls), "__call__")
            )
            init.return_value = unittest.mock.Mock()

            new = stack.enter_context(
                unittest.mock.patch.object(Cls, "__new__")
            )
            new.return_value = instance

            gen = Cls.parse_events((None, "foo", {}), self.ctx)
            next(gen)
            with self.assertRaises(StopIteration) as ctx:
                gen.send(("end", ))

        self.assertSequenceEqual(
            [
            ],
            init.mock_calls,
            "construction happened through init"
        )

        self.assertIs(
            instance,
            ctx.exception.value
        )

        self.assertSequenceEqual(
            [
                unittest.mock.call(Cls),
                unittest.mock.call().validate(),
                unittest.mock.call().xso_after_load(),
            ],
            new.mock_calls
        )

    def test_default_declare_ns_to_empty_dict_for_namespaceless_tag(self):
        class Cls(metaclass=xso_model.XMLStreamClass):
            TAG = "foo"

        self.assertDictEqual(Cls.DECLARE_NS, {})

    def test_default_declare_ns_to_declare_tag_namespace(self):
        class Cls(metaclass=xso_model.XMLStreamClass):
            TAG = ("uri:foo", "foo")

        self.assertDictEqual(Cls.DECLARE_NS, {
            None: "uri:foo"
        })

    def test_do_not_declare_ns_if_tag_is_not_set(self):
        class ClsA(metaclass=xso_model.XMLStreamClass):
            TAG = ("uri:foo", "foo")

        class ClsB(metaclass=xso_model.XMLStreamClass):
            pass

        self.assertNotIn(
            "DECLARE_NS",
            ClsB.__dict__
        )

    def test_user_defined_declare_ns_takes_precedence(self):
        d = dict()

        class Cls(metaclass=xso_model.XMLStreamClass):
            TAG = ("uri:foo", "foo")

            DECLARE_NS = d

        self.assertIs(Cls.DECLARE_NS, d)

    def test_user_defined_declare_ns_takes_precedence_in_inheritance(self):
        d = dict()

        class ClsA(metaclass=xso_model.XMLStreamClass):
            DECLARE_NS = d

        class ClsB(ClsA):
            TAG = ("uri:foo", "foo")

        self.assertIs(ClsA.DECLARE_NS, d)
        self.assertIs(ClsB.DECLARE_NS, d)


class TestCapturingXMLStreamClass(unittest.TestCase):
    def test_parse_events_uses_capture(self):
        class Cls(metaclass=xso_model.CapturingXMLStreamClass):
            pass

        capture_events_mock = unittest.mock.Mock()
        result = unittest.mock.Mock()

        def capture_events(receiver, dest):
            mock = capture_events_mock(receiver, dest)
            mock.next()
            mock.send((yield))
            return result

        ev_args = [1, 2, 3]
        parent_ctx = object()
        with contextlib.ExitStack() as stack:
            parse_events = stack.enter_context(
                unittest.mock.patch.object(
                    xso_model.XMLStreamClass,
                    "parse_events")
            )

            self.assertIsInstance(Cls, xso_model.XMLStreamClass)

            stack.enter_context(
                unittest.mock.patch(
                    "aioxmpp.xso.model.capture_events",
                    new=capture_events
                )
            )

            i = Cls.parse_events(ev_args, parent_ctx)
            next(i)

        parse_events.assert_called_with(ev_args, parent_ctx)

        self.assertSequenceEqual(
            capture_events_mock.mock_calls,
            [
                unittest.mock.call(parse_events(), unittest.mock.ANY),
                unittest.mock.call().next(),
            ]
        )
        _, (_, dest), _ = capture_events_mock.mock_calls[0]
        capture_events_mock.mock_calls.clear()

        self.assertSequenceEqual(
            dest,
            [
                ("start", )+tuple(ev_args)
            ]
        )

        with self.assertRaises(StopIteration) as ctx:
            i.send("foo")

        self.assertSequenceEqual(
            capture_events_mock.mock_calls,
            [
                unittest.mock.call().send("foo"),
            ]
        )
        capture_events_mock.mock_calls.clear()

        result._set_captured_events.assert_called_with(dest)

        self.assertIs(ctx.exception.value, result)


class TestXSO(XMLTestCase):
    def _unparse_test(self, obj, tree):
        parent = etree.Element("foo")
        unparse_to_node(obj, parent)
        self.assertSubtreeEqual(
            tree,
            parent,
            strict_ordering=False
        )

    def setUp(self):
        class Cls(xso.XSO):
            TAG = "bar"

        self.Cls = Cls
        self.obj = Cls()

    def test_error_handler(self):
        self.obj.xso_error_handler(
            None,
            None,
            None)

    def test_policies(self):
        self.assertEqual(
            xso.UnknownChildPolicy.DROP,
            self.Cls.UNKNOWN_CHILD_POLICY)
        self.assertEqual(
            xso.UnknownAttrPolicy.DROP,
            self.Cls.UNKNOWN_ATTR_POLICY)

    def test_declare_ns(self):
        self.assertEqual(self.Cls.DECLARE_NS, {})

        class Cls(xso.XSO):
            TAG = ("uri:foo", "foo")

            DECLARE_NS = collections.OrderedDict([
                (None, "uri:foo"),
                ("bar", "uri:bar"),
            ])

        sink = unittest.mock.MagicMock()

        obj = Cls()
        obj.xso_serialise_to_sax(sink)

        self.assertSequenceEqual(
            [
                unittest.mock.call.startPrefixMapping(None, "uri:foo"),
                unittest.mock.call.startPrefixMapping("bar", "uri:bar"),
                unittest.mock.call.startElementNS(
                    ("uri:foo", "foo"), None, {}),
                unittest.mock.call.endElementNS(("uri:foo", "foo"), None),
                unittest.mock.call.endPrefixMapping(None),
                unittest.mock.call.endPrefixMapping("bar"),
            ],
            sink.mock_calls
        )

    def test_property_storage(self):
        self.obj._xso_contents["key"] = "value"

    def test_unparse_to_node_create_node(self):
        self._unparse_test(
            self.obj,
            etree.fromstring("<foo><bar/></foo>")
        )

    def test_unparse_to_node_handle_text(self):
        class Cls(xso.XSO):
            TAG = "bar"
            text = xso.Text()

        obj = Cls()
        obj.text = "foobar"

        self._unparse_test(
            obj,
            etree.fromstring("<foo><bar>foobar</bar></foo>")
        )

    def test_unparse_to_node_handle_child(self):
        class ClsLeaf(xso.XSO):
            TAG = "baz"
            text = xso.Text()

        class Cls(xso.XSO):
            TAG = "bar"
            child = xso.Child([ClsLeaf])

        obj = Cls()
        obj.child = ClsLeaf()
        obj.child.text = "fnord"

        self._unparse_test(
            obj,
            etree.fromstring("<foo><bar><baz>fnord</baz></bar></foo>")
        )

    def test_unparse_to_node_handle_child_list(self):
        class ClsLeaf(xso.XSO):
            TAG = "baz"
            text = xso.Text()

            def __init__(self, text=None):
                super().__init__()
                self.text = text

        class Cls(xso.XSO):
            TAG = "bar"
            children = xso.ChildList([ClsLeaf])

        obj = Cls()
        obj.children.append(ClsLeaf("a"))
        obj.children.append(ClsLeaf("b"))
        obj.children.append(ClsLeaf("c"))

        self._unparse_test(
            obj,
            etree.fromstring(
                "<foo><bar><baz>a</baz><baz>b</baz><baz>c</baz></bar></foo>"
            )
        )

    def test_unparse_to_node_handle_child_text(self):
        class Cls(xso.XSO):
            TAG = "bar"
            body = xso.ChildText("body")

        obj = Cls()
        obj.body = "foobar"

        self._unparse_test(
            obj,
            etree.fromstring("<foo><bar><body>foobar</body></bar></foo>")
        )

    def test_unparse_to_node_handle_collector(self):
        class Cls(xso.XSO):
            TAG = "bar"
            dump = xso.Collector()

        obj = Cls()
        obj.dump.append(etree.fromstring("<foo/>"))
        obj.dump.append(etree.fromstring("<fnord/>"))

        self._unparse_test(
            obj,
            etree.fromstring("<foo><bar><foo/><fnord/></bar></foo>")
        )

    def test_unparse_to_node_handle_child_map(self):
        class ClsLeafA(xso.XSO):
            TAG = "baz"
            text = xso.Text()

            def __init__(self, text=None):
                super().__init__()
                self.text = text

        class ClsLeafB(xso.XSO):
            TAG = "fnord"
            text = xso.Text()

            def __init__(self, text=None):
                super().__init__()
                self.text = text

        class Cls(xso.XSO):
            TAG = "bar"
            children = xso.ChildMap([ClsLeafA, ClsLeafB])

        obj = Cls()
        obj.children[ClsLeafA.TAG].append(ClsLeafA("a"))
        obj.children[ClsLeafA.TAG].append(ClsLeafA("b"))
        obj.children[ClsLeafB.TAG].append(ClsLeafB("1"))

        self._unparse_test(
            obj,
            etree.fromstring(
                "<foo><bar>"
                "<baz>a</baz>"
                "<baz>b</baz>"
                "<fnord>1</fnord>"
                "</bar></foo>"
            )
        )

    def test_unparse_to_node_handle_attr(self):
        class Cls(xso.XSO):
            TAG = "bar"
            attr = xso.Attr("baz")

        obj = Cls()
        obj.attr = "fnord"

        self._unparse_test(
            obj,
            etree.fromstring("<foo><bar baz='fnord'/></foo>")
        )

    def test_validate_calls_validate_on_all_child_descriptors(self):
        class Foo(xso.XSO):
            TAG = "foo"

            attr = xso.Attr("baz")
            child = xso.Child([])

        obj = Foo()

        with contextlib.ExitStack() as stack:
            attr_validate = stack.enter_context(
                unittest.mock.patch.object(Foo.attr.xq_descriptor,
                                           "validate_contents")
            )
            child_validate = stack.enter_context(
                unittest.mock.patch.object(Foo.child.xq_descriptor,
                                           "validate_contents")
            )

            obj.validate()

        self.assertSequenceEqual(
            [
            ],
            attr_validate.mock_calls
        )

        self.assertSequenceEqual(
            [
                unittest.mock.call(obj),
            ],
            child_validate.mock_calls
        )

    def test_init_takes_no_arguments(self):
        with self.assertRaises(TypeError):
            xso.XSO("foo")
        with self.assertRaises(TypeError):
            xso.XSO(bar="foo")

    def test_init_forwards_to_base_class(self):
        class Test:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        class TestXSO(xso.XSO, Test):
            pass

        obj = TestXSO("foo", bar="baz")
        self.assertEqual(
            obj.args,
            ("foo",)
        )
        self.assertDictEqual(
            obj.kwargs,
            {"bar": "baz"}
        )

    def test_copy_does_not_call_init_and_copies_props(self):
        base = unittest.mock.Mock()
        class Test(xso.XSO):
            a = xso.Attr("foo")

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                base.init(*args, **kwargs)

        t = Test()
        t.a = "foo"

        base.mock_calls.clear()

        t2 = copy.copy(t)
        self.assertFalse(base.mock_calls)
        self.assertIsNot(t._xso_contents, t2._xso_contents)
        self.assertEqual(t._xso_contents, t2._xso_contents)

    def test_deepcopy_does_not_call_init_and_deepcopies_props(self):
        base = unittest.mock.Mock()
        class Child(xso.XSO):
            TAG = (None, "foo")

        class Test(xso.XSO):
            a = xso.Child([Child])

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                base.init(*args, **kwargs)

        t = Test()
        t.a = Child()

        base.mock_calls.clear()

        t2 = copy.deepcopy(t)
        self.assertFalse(base.mock_calls)
        self.assertIsNot(t._xso_contents, t2._xso_contents)
        self.assertIsNot(t._xso_contents[Test.a.xq_descriptor],
                         t2._xso_contents[Test.a.xq_descriptor])

    def test_is_weakrefable(self):
        i = xso.XSO()

        import weakref
        r = weakref.ref(i)

        self.assertIs(r(), i)

    def tearDown(self):
        del self.obj
        del self.Cls


class TestCapturingXSO(unittest.TestCase):
    def test_is_capturing_xml_stream_class(self):
        self.assertIsInstance(
            xso_model.CapturingXSO,
            xso_model.CapturingXMLStreamClass
        )

    def test_is_xso(self):
        self.assertTrue(
            issubclass(xso_model.CapturingXSO, xso_model.XSO)
        )

    def test_is_abstract(self):
        with self.assertRaisesRegex(TypeError,
                                    r"abstract methods _set_captured_events"):
            xso_model.CapturingXSO()


class TestXSOList(unittest.TestCase):
    def setUp(self):
        self.l = xso_model.XSOList()

        class ClsA(xso.XSO):
            TAG = ("uri:foo", "foo")

            lang = xso.LangAttr()
            foo = xso.Attr("foo")

        class ClsB(xso.XSO):
            TAG = ("uri:foo", "bar")

            lang = xso.LangAttr()
            bar = xso.Attr("bar")

        self.ClsA = ClsA
        self.ClsB = ClsB

        self.a_s = [self.ClsA() for i in range(3)]
        self.b_s = [self.ClsB() for i in range(2)]

        self.l.extend(self.a_s[:2])
        self.l.append(self.b_s[0])
        self.l.extend(self.a_s[2:])
        self.l.append(self.b_s[1])

    def test_is_mutable_sequence(self):
        self.assertIsInstance(self.l, collections.abc.MutableSequence)

    def test_empty_filtered_is_noop(self):
        self.assertSequenceEqual(
            self.l,
            self.l.filtered()
        )
        self.assertIsNot(self.l, self.l.filtered())

    def test_filter_by_type(self):
        self.assertSequenceEqual(
            self.a_s,
            self.l.filtered(type_=self.ClsA)
        )

        self.assertSequenceEqual(
            self.b_s,
            self.l.filtered(type_=self.ClsB)
        )

    def test_filter_by_language(self):
        self.a_s[0].lang = structs.LanguageTag.fromstr("en-GB")
        self.a_s[1].lang = structs.LanguageTag.fromstr("en-gb")
        self.a_s[2].lang = structs.LanguageTag.fromstr("de-DE")

        self.b_s[0].lang = structs.LanguageTag.fromstr("fr")
        self.b_s[1].lang = structs.LanguageTag.fromstr("en")

        self.assertSequenceEqual(
            [self.a_s[0], self.a_s[1]],
            self.l.filtered(lang=structs.LanguageRange.fromstr("en-GB"))
        )
        self.assertSequenceEqual(
            [self.b_s[1]],
            self.l.filtered(lang=structs.LanguageRange.fromstr("en-us"))
        )

        self.assertSequenceEqual(
            [self.b_s[1]],
            self.l.filtered(lang=structs.LanguageRange.fromstr("en"))
        )

    def test_filter_by_languages(self):
        self.a_s[0].lang = structs.LanguageTag.fromstr("en-GB")
        self.a_s[1].lang = structs.LanguageTag.fromstr("en-gb")
        self.a_s[2].lang = structs.LanguageTag.fromstr("de-DE")

        self.b_s[0].lang = structs.LanguageTag.fromstr("fr")
        self.b_s[1].lang = structs.LanguageTag.fromstr("en")

        self.assertSequenceEqual(
            [self.a_s[2]],
            self.l.filtered(lang=[structs.LanguageRange.fromstr("in"),
                                  structs.LanguageRange.fromstr("de-ch")])
        )

    def test_filter_by_languages_skips_None(self):
        self.a_s[0].lang = structs.LanguageTag.fromstr("en-GB")
        self.a_s[1].lang = structs.LanguageTag.fromstr("en-gb")
        self.a_s[2].lang = structs.LanguageTag.fromstr("de-DE")

        self.b_s[0].lang = structs.LanguageTag.fromstr("fr")
        self.b_s[1].lang = None

        self.assertSequenceEqual(
            [self.a_s[2]],
            self.l.filtered(lang=[structs.LanguageRange.fromstr("in"),
                                  structs.LanguageRange.fromstr("de-ch")])
        )

    def test_filter_by_generic_attribute(self):
        self.a_s[0].foo = "a"
        self.a_s[1].foo = "b"
        self.a_s[2].foo = "b"

        self.b_s[0].bar = "1"
        self.b_s[1].bar = "2"

        self.assertSequenceEqual(
            [self.a_s[1], self.a_s[2]],
            self.l.filtered(attrs={"foo": "b"})
        )

        self.assertSequenceEqual(
            [self.a_s[0]],
            self.l.filtered(attrs={"foo": "a"})
        )

    def test_filter_by_generic_attribute_is_dynamic_generator(self):
        self.a_s[0].foo = "a"
        self.a_s[1].foo = "b"
        self.a_s[2].foo = "b"

        gen = self.l.filter(attrs={"foo": "a"})
        self.assertIs(self.a_s[0], next(gen))
        self.a_s[1].foo = "a"
        self.assertIs(self.a_s[1], next(gen))
        self.a_s[2].foo = "a"
        self.assertIs(self.a_s[2], next(gen))

        with self.assertRaises(StopIteration):
            next(gen)

    def tearDown(self):
        del self.l
        del self.a_s
        del self.b_s


class Test_PropBase(unittest.TestCase):
    def setUp(self):
        self.default = object()

        self.prop = xso_model._PropBase(
            default=self.default
        )

        class Cls(xso.XSO):
            prop = self.prop

        self.Cls = Cls
        self.obj = Cls()

    def test_get_unset_without_default(self):
        class Cls(xso.XSO):
            prop = xso_model._PropBase()

        with self.assertRaisesRegex(
                AttributeError,
                "attribute is unset"):
            Cls().prop

    def test_set_get_cycle(self):
        self.obj.prop = "foo"
        self.assertEqual(
            "foo",
            self.obj.prop)

    def test_get_on_class(self):
        with unittest.mock.patch(
                "aioxmpp.xso.query.BoundDescriptor") as BoundDescriptor:
            result = self.Cls.prop

        BoundDescriptor.assert_called_with(
            self.Cls,
            self.prop,
            xso_query.GetDescriptor,
        )

        self.assertEqual(
            result,
            BoundDescriptor(),
        )

    def test_mark_incomplete(self):
        self.Cls.prop.mark_incomplete(self.obj)
        with self.assertRaisesRegex(
                AttributeError,
                "attribute value is incomplete"):
            self.obj.prop

    def test_mark_incomplete_is_resolved_after_write(self):
        self.Cls.prop.mark_incomplete(self.obj)
        self.obj.prop = "foo"
        self.assertEqual(self.obj.prop, "foo")

    def test_validator_recv(self):
        validator = unittest.mock.MagicMock()
        instance = make_instance_mock()

        prop = xso_model._PropBase(
            default=self.default,
            validator=validator,
            validate=xso.ValidateMode.FROM_RECV)

        prop._set_from_recv(instance, "foo")
        self.assertDictEqual(
            {
                prop: "foo",
            },
            instance._xso_contents
        )

        prop._set_from_code(instance, "bar")
        self.assertDictEqual(
            {
                prop: "bar",
            },
            instance._xso_contents
        )

        validator.validate.return_value = False
        with self.assertRaises(ValueError):
            prop._set_from_recv(instance, "baz")

        self.assertSequenceEqual(
            [
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("foo"),
                unittest.mock.call.validate().__bool__(),
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("baz"),
            ],
            validator.mock_calls)

    def test_validator_recv_ignores_default(self):
        validator = unittest.mock.MagicMock()
        instance = make_instance_mock()

        prop = xso_model._PropBase(
            default=self.default,
            validator=validator,
            validate=xso.ValidateMode.FROM_RECV)

        prop._set_from_recv(instance, self.default)
        validator.validate.assert_not_called()

    def test_validator_code(self):
        validator = unittest.mock.MagicMock()
        instance = make_instance_mock()

        prop = xso_model._PropBase(
            default=self.default,
            validator=validator,
            validate=xso.ValidateMode.FROM_CODE)

        prop._set_from_recv(instance, "foo")
        self.assertDictEqual(
            {
                prop: "foo",
            },
            instance._xso_contents
        )

        prop._set_from_code(instance, "bar")
        self.assertDictEqual(
            {
                prop: "bar",
            },
            instance._xso_contents
        )

        validator.validate.return_value = False
        with self.assertRaises(ValueError):
            prop._set_from_code(instance, "baz")

        self.assertSequenceEqual(
            [
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("bar"),
                unittest.mock.call.validate().__bool__(),
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("baz"),
            ],
            validator.mock_calls)

    def test_validator_code_ignores_default(self):
        validator = unittest.mock.MagicMock()
        instance = make_instance_mock()

        prop = xso_model._PropBase(
            default=self.default,
            validator=validator,
            validate=xso.ValidateMode.FROM_CODE)

        prop._set_from_code(instance, self.default)
        validator.validate.assert_not_called()

    def test_validator_always(self):
        validator = unittest.mock.MagicMock()
        instance = make_instance_mock()

        prop = xso_model._PropBase(
            default=self.default,
            validator=validator,
            validate=xso.ValidateMode.ALWAYS)

        prop._set_from_recv(instance, "foo")
        self.assertDictEqual(
            {
                prop: "foo",
            },
            instance._xso_contents
        )

        prop._set_from_code(instance, "bar")
        self.assertDictEqual(
            {
                prop: "bar",
            },
            instance._xso_contents
        )

        validator.validate.return_value = False
        with self.assertRaises(ValueError):
            prop._set_from_recv(instance, "baz")

        with self.assertRaises(ValueError):
            prop._set_from_code(instance, "fnord")

        self.assertSequenceEqual(
            [
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("foo"),
                unittest.mock.call.validate().__bool__(),
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("bar"),
                unittest.mock.call.validate().__bool__(),
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("baz"),
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("fnord"),
            ],
            validator.mock_calls)

    def test_descriptor_access_goes_through_code_setter(self):
        validator = unittest.mock.MagicMock()

        class Cls(xso.XSO):
            prop = xso_model._PropBase(
                default=self.default,
                validator=validator,
                validate=xso.ValidateMode.FROM_CODE)

        obj = Cls()
        obj.prop = "foo"
        self.assertEqual(
            "foo",
            obj.prop)

        validator.validate.return_value = False
        with self.assertRaises(ValueError):
            obj.prop = "bar"

        self.assertEqual(
            "foo",
            obj.prop)

        self.assertSequenceEqual(
            [
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("foo"),
                unittest.mock.call.validate().__bool__(),
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("bar"),
            ],
            validator.mock_calls)

    def test_validate_raises_if_unset_and_undefaulted(self):
        prop = xso_model._PropBase()
        instance = make_instance_mock()

        with self.assertRaisesRegex(ValueError, "attribute is unset"):
            prop.validate_contents(instance)

    def tearDown(self):
        del self.obj
        del self.Cls
        del self.default


class Test_TypedPropBase(unittest.TestCase):
    def test_coerce_on_code_access(self):
        type_ = unittest.mock.MagicMock()
        instance = make_instance_mock()

        prop = xso_model._TypedPropBase(
            default=None,
            type_=type_)

        prop._set_from_code(instance, "bar")

        type_.coerce.assert_called_once_with("bar")

        self.assertDictEqual(
            {
                prop: type_.coerce(),
            },
            instance._xso_contents
        )

    def test_do_not_coerce_default(self):
        type_ = unittest.mock.MagicMock()
        instance = make_instance_mock()

        prop = xso_model._TypedPropBase(
            default=unittest.mock.sentinel.foo,
            type_=type_)

        prop._set_from_code(
            instance,
            unittest.mock.sentinel.foo
        )

        self.assertSequenceEqual(
            [
            ],
            type_.mock_calls
        )

        self.assertDictEqual(
            {
                prop: unittest.mock.sentinel.foo
            },
            instance._xso_contents
        )


class TestText(XMLTestCase):
    def setUp(self):
        class ClsA(xso.XSO):
            test_str = xso.Text(default="bar")

        class ClsB(xso.XSO):
            test_int = xso.Text(type_=xso.Integer())

        self.ClsA = ClsA
        self.ClsB = ClsB
        self.obja = ClsA()
        self.objb = ClsB()

    def test_default(self):
        self.assertEqual(
            "bar",
            self.obja.test_str)

    def test_string_from_node(self):
        self.ClsA.test_str.from_value(
            self.obja,
            "foo"
        )
        self.assertEqual(
            "foo",
            self.obja.test_str)

    def test_int_from_node(self):
        self.ClsB.test_int.from_value(
            self.objb,
            "123",
        )
        self.assertEqual(
            123,
            self.objb.test_int)

    def test_int_to_sax(self):
        dest = unittest.mock.MagicMock()
        self.objb.test_int = 123
        self.ClsB.test_int.to_sax(
            self.objb,
            dest)
        self.assertEqual(
            [
                unittest.mock.call.characters("123"),
            ],
            dest.mock_calls)

    def test_validates(self):
        validator = unittest.mock.MagicMock()
        instance = make_instance_mock()

        prop = xso.Text(validator=validator)

        validator.validate.return_value = True
        prop.from_value(instance, "foo")

        validator.validate.return_value = False
        with self.assertRaises(ValueError):
            prop.from_value(instance, "foo")

        self.assertSequenceEqual(
            [
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("foo"),
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("foo"),
            ],
            validator.mock_calls)

    def test_coerces(self):
        type_ = unittest.mock.MagicMock()
        instance = make_instance_mock()

        prop = xso.Text(type_=type_)
        prop.__set__(instance, "foo")

        type_.coerce.assert_called_once_with("foo")

    def test_to_sax_unset(self):
        instance = make_instance_mock()

        prop = xso.Text(default="foo")
        dest = unittest.mock.MagicMock()
        prop.to_sax(instance, dest)
        self.assertSequenceEqual(
            [
                unittest.mock.call.characters("foo"),
            ],
            dest.mock_calls)

        instance._xso_contents = {prop: None}
        dest = unittest.mock.MagicMock()
        prop.to_sax(instance, dest)
        self.assertSequenceEqual(
            [
            ],
            dest.mock_calls)

    def tearDown(self):
        del self.obja
        del self.objb
        del self.ClsA
        del self.ClsB


class TestChild(XMLTestCase):
    def setUp(self):
        class ClsLeaf(xso.XSO, protect=False):
            TAG = "bar"

        class ClsA(xso.XSO, protect=False):
            TAG = "foo"
            test_child = xso.Child([ClsLeaf])

        self.ClsLeaf = ClsLeaf
        self.ClsA = ClsA

        self.ctx = xso_model.Context()

    def test_default_default_is_None(self):
        prop = xso.Child([])
        self.assertIs(prop.default, None)
        prop = xso.Child([], required=False)
        self.assertIs(prop.default, None)

    def test_default_for_required_is_no_default(self):
        prop = xso.Child([], required=True)
        self.assertIs(prop.default, xso.NO_DEFAULT)

    def test_default_required_is_not_writable(self):
        prop = xso.Child([], required=True)
        with self.assertRaises(AttributeError):
            prop.required = False

    def test_default_required_reflects_argument(self):
        prop = xso.Child([], required=True)
        self.assertIs(prop.required, True)
        prop = xso.Child([], required="")
        self.assertIs(prop.required, False)

    def test_match_map(self):
        self.assertDictEqual(
            {self.ClsLeaf.TAG: self.ClsLeaf},
            self.ClsA.test_child.get_tag_map()
        )

    def test_default_strict_is_False(self):
        prop = xso.Child([])
        self.assertIs(prop.strict, False)

    def test_strict_controllable_from_init(self):
        prop = xso.Child([], strict=True)
        self.assertIs(prop.strict, True)

    def test_forbid_duplicate_tags(self):
        class ClsLeaf2(xso.XSO):
            TAG = "bar"

        with self.assertRaisesRegex(ValueError, "ambiguous children"):
            xso.Child([self.ClsLeaf, ClsLeaf2])

    def test__register(self):
        class ClsLeaf2(xso.XSO):
            TAG = "baz"

        self.ClsA.test_child._register(ClsLeaf2)
        self.assertDictEqual(
            {
                (None, "bar"): self.ClsLeaf,
                (None, "baz"): ClsLeaf2
            },
            self.ClsA.test_child.get_tag_map()
        )

        class ClsLeafConflict(xso.XSO):
            TAG = "baz"

        with self.assertRaisesRegex(ValueError, "ambiguous children"):
            self.ClsA.test_child._register(ClsLeafConflict)

    def test_from_events(self):
        dest = []

        def mock_fun(ev_args, ctx):
            dest.append(ev_args)
            while True:
                value = yield
                dest.append(value)
                if value[0] == "stop":
                    return "bar"

        Cls = unittest.mock.MagicMock()
        Cls.TAG = None, "foo"
        Cls.parse_events = mock_fun

        prop = xso.Child([Cls])

        instance = make_instance_mock()

        gen = prop.from_events(instance, (None, "foo", {}), self.ctx)
        next(gen)
        with self.assertRaises(StopIteration) as ctx:
            gen.send(("stop",))
        self.assertEqual(
            "bar",
            ctx.exception.value
        )
        self.assertSequenceEqual(
            [
                (None, "foo", {}),
                ("stop",)
            ],
            dest)
        self.assertDictEqual(
            {prop: "bar"},
            instance._xso_contents)

    def test_to_sax(self):
        dest = unittest.mock.MagicMock()
        obj = self.ClsA()
        obj.test_child = unittest.mock.MagicMock()
        self.ClsA.test_child.to_sax(obj, dest)
        obj.test_child.xso_serialise_to_sax.assert_called_once_with(dest)

    def test_to_sax_unset(self):
        dest = unittest.mock.MagicMock()
        obj = self.ClsA()
        obj.test_child = None
        self.ClsA.test_child.to_sax(obj, dest)
        self.assertSequenceEqual(
            [
            ],
            dest.mock_calls)

    def test_validate_contents_recurses(self):
        obj = self.ClsA()
        child = self.ClsLeaf()
        obj.test_child = child

        with unittest.mock.patch.object(child, "validate") as validate:
            self.ClsA.test_child.validate_contents(obj)

        self.assertSequenceEqual(
            [
                unittest.mock.call(),
            ],
            validate.mock_calls
        )

    def test_validate_contents_passes_for_None(self):
        obj = self.ClsA()
        obj.test_child = None

        self.ClsA.test_child.validate_contents(obj)

    def test_validate_contents_rejects_None_if_required(self):
        class Cls(xso.XSO):
            prop = xso.Child([], required=True)

        with self.assertRaisesRegex(ValueError,
                                    "missing required member"):
            Cls.prop.validate_contents(Cls())

    def test_cannot_assign_None_if_required(self):
        class Cls(xso.XSO):
            prop = xso.Child([], required=True)

        instance = Cls()
        with self.assertRaisesRegex(ValueError,
                                    "cannot set required member to None"):
            instance.prop = None

    def test_cannot_delete_if_required(self):
        class Cls(xso.XSO):
            prop = xso.Child([], required=True)

        instance = Cls()
        with self.assertRaisesRegex(AttributeError,
                                    "cannot delete required member"):
            del instance.prop

    def test_cannot_access_if_required_and_unset(self):
        class Cls(xso.XSO):
            prop = xso.Child([], required=True)

        instance = Cls()
        with self.assertRaisesRegex(AttributeError,
                                    "attribute is unset"):
            instance.prop

    def test_delete_sets_to_None_if_not_required(self):
        class Cls(xso.XSO):
            prop = xso.Child([self.ClsA], required=False)

        instance = Cls()
        del instance.prop
        instance.prop = self.ClsA()
        del instance.prop
        self.assertIsNone(instance.prop)

    def test_strict_rejects_non_registered_classes(self):
        class Cls(xso.XSO):
            prop = xso.Child([], strict=True)

        instance = Cls()
        with self.assertRaisesRegex(
                TypeError,
                "<class 'object'> object is not a valid value"):
            instance.prop = object()

    def test_strict_rejects_allows_reistered_classes(self):
        class Child(xso.XSO):
            TAG = "test", "test"

        class Cls(xso.XSO):
            prop = xso.Child([Child], strict=True)

        child = Child()

        instance = Cls()
        instance.prop = child
        self.assertIs(child, instance.prop)

    def test_strict_rejects_unregistered_subclasses(self):
        class Child(xso.XSO):
            TAG = "test", "test"

        class SubChild(xso.XSO):
            pass

        class Cls(xso.XSO):
            prop = xso.Child([Child], strict=True)

        instance = Cls()
        with self.assertRaisesRegex(
                TypeError,
                "<class '.+\.SubChild'> object is not a valid value"):
            instance.prop = SubChild()

    def test_strict_allows_none_if_not_required(self):
        class Cls(xso.XSO):
            prop = xso.Child([], strict=True, required=False)

        instance = Cls()
        instance.prop = None

    def tearDown(self):
        del self.ClsA
        del self.ClsLeaf


class TestChildList(XMLTestCase):
    def setUp(self):
        class ClsLeafA(xso.XSO):
            TAG = "bar"

        class ClsLeafB(xso.XSO):
            TAG = "baz"

        self.prop = xso.ChildList([ClsLeafA, ClsLeafB])

        class Cls(xso.XSO):
            TAG = "foo"
            children = self.prop

        self.Cls = Cls
        self.ClsLeafA = ClsLeafA
        self.ClsLeafB = ClsLeafB

        self.ctx = xso_model.Context()

    def test_get_on_class_returns_BoundDescriptor(self):
        with unittest.mock.patch(
                "aioxmpp.xso.query.BoundDescriptor") as BoundDescriptor:
            result = self.Cls.children

        BoundDescriptor.assert_called_with(
            self.Cls,
            self.prop,
            xso_query.GetSequenceDescriptor,
        )

        self.assertEqual(
            result,
            BoundDescriptor(),
        )

    def test_from_events(self):
        results = []

        def catch_result(value):
            results.append(value)

        obj = self.Cls()

        sd = xso.SAXDriver(
            functools.partial(
                from_wrapper,
                self.Cls.children.from_events,
                obj,
                ctx=self.ctx),
            on_emit=catch_result
        )

        subtrees = [etree.Element(s) for s in ["bar", "bar", "baz", "bar"]]

        for subtree in subtrees:
            lxml.sax.saxify(subtree, sd)

        self.assertSequenceEqual(
            results,
            obj.children)

        self.assertIsInstance(obj.children, xso_model.XSOList)

        self.assertEqual(4, len(obj.children))

        self.assertIsInstance(obj.children[0], self.ClsLeafA)
        self.assertIsInstance(obj.children[1], self.ClsLeafA)
        self.assertIsInstance(obj.children[2], self.ClsLeafB)
        self.assertIsInstance(obj.children[3], self.ClsLeafA)

    def test_to_sax(self):
        dest = unittest.mock.MagicMock()

        obj = self.Cls()
        obj.children.append(self.ClsLeafA())
        obj.children.append(self.ClsLeafB())
        obj.children.append(self.ClsLeafA())
        obj.children.append(self.ClsLeafA())

        self.Cls.children.to_sax(obj, dest)

        self.assertSequenceEqual(
            [
                unittest.mock.call.startElementNS((None, "bar"), None, {}),
                unittest.mock.call.endElementNS((None, "bar"), None),
                unittest.mock.call.startElementNS((None, "baz"), None, {}),
                unittest.mock.call.endElementNS((None, "baz"), None),
                unittest.mock.call.startElementNS((None, "bar"), None, {}),
                unittest.mock.call.endElementNS((None, "bar"), None),
                unittest.mock.call.startElementNS((None, "bar"), None, {}),
                unittest.mock.call.endElementNS((None, "bar"), None),
            ],
            dest.mock_calls)

    def test_assign_enforces_list(self):
        obj = self.Cls()
        with self.assertRaises(TypeError):
            obj.children = 123
        with self.assertRaises(TypeError):
            obj.children = "foo"
        l = []
        obj.children = l
        self.assertIs(
            l,
            obj.children
        )

    def test_validate_contents_recurses_to_all_children(self):
        obj = self.Cls()
        children = [
            self.ClsLeafA(),
            self.ClsLeafB(),
            self.ClsLeafA(),
        ]
        obj.children.extend(children)

        with contextlib.ExitStack() as stack:
            a_validate = stack.enter_context(
                unittest.mock.patch.object(self.ClsLeafA, "validate")
            )
            b_validate = stack.enter_context(
                unittest.mock.patch.object(self.ClsLeafB, "validate")
            )

            obj.validate()

        self.assertSequenceEqual(
            [
                unittest.mock.call(),
                unittest.mock.call(),
            ],
            a_validate.mock_calls
        )

        self.assertSequenceEqual(
            [
                unittest.mock.call(),
            ],
            b_validate.mock_calls
        )

    def tearDown(self):
        del self.ClsLeafB
        del self.ClsLeafA
        del self.Cls


class TestCollector(XMLTestCase):
    def setUp(self):
        self.ctx = xso_model.Context()

    def test_get_on_class_returns_BoundDescriptor(self):
        prop = xso.Collector()

        class Cls(xso.XSO):
            children = prop

        with unittest.mock.patch(
                "aioxmpp.xso.query.BoundDescriptor") as BoundDescriptor:
            result = Cls.children

        BoundDescriptor.assert_called_with(
            Cls,
            prop,
            xso_query.GetSequenceDescriptor,
        )

        self.assertEqual(
            result,
            BoundDescriptor(),
        )

    def test_from_events(self):
        instance = make_instance_mock()

        prop = xso.Collector()

        subtree1 = etree.fromstring("<foo/>")
        subtree2 = etree.fromstring("<bar a='baz'>fnord</bar>")
        subtree3 = etree.fromstring(
            "<baz>prefix: <a/>"
            "<b c='something'/>"
            "<d i='am running out of'>dummy texts</d>"
            "to insert</baz>")

        subtrees = [subtree1, subtree2, subtree3]

        for subtree in subtrees:
            drive_from_events(prop.from_events, instance, subtree,
                              self.ctx)

        for result, subtree in zip(instance._xso_contents[prop],
                                   subtrees):
            self.assertSubtreeEqual(
                subtree,
                result)

    def test_assign_raises(self):
        class Cls(xso.XSO):
            TAG = ("foo", "bar")
            children = xso.Collector()

        obj = Cls()
        with self.assertRaises(AttributeError):
            obj.children = 123
        with self.assertRaises(AttributeError):
            obj.children = "foo"
        with self.assertRaises(AttributeError):
            obj.children = []

    def test_to_node(self):
        prop = xso.Collector()

        subtree1 = etree.fromstring("<foo/>")
        subtree2 = etree.fromstring("<bar a='baz'>fnord</bar>")
        subtree3 = etree.fromstring(
            "<baz><a/>"
            "<b c='something'/>"
            "<d i='am running out of'>dummy texts</d>"
            "to insert</baz>")

        instance = make_instance_mock({
            prop: [
                subtree1,
                subtree2,
                subtree3,
            ]
        })

        parent_compare = etree.Element("root")
        parent_compare.extend([subtree1, subtree2, subtree3])

        parent_generated = etree.Element("root")
        prop.to_node(instance, parent_generated)

        self.assertSubtreeEqual(
            parent_compare,
            parent_generated)

    def test_to_sax_does_not_call_startDocument(self):
        prop = xso.Collector()

        subtree1 = etree.fromstring("<foo xmlns='uri:foo'/>")
        subtree2 = etree.fromstring("<bar xmlns='uri:bar' a='baz'>fnord</bar>")
        subtree3 = etree.fromstring(
            "<baz><a/>"
            "<b c='something'/>"
            "<d i='am running out of'>dummy texts</d>"
            "to insert</baz>")

        instance = make_instance_mock({
            prop: [
                subtree1,
                subtree2,
                subtree3,
            ]
        })

        sax_receiver = unittest.mock.Mock()

        prop.to_sax(instance, sax_receiver)
        sax_receiver.startDocument.assert_not_called()
        sax_receiver.startPrefixMapping.assert_not_called()
        sax_receiver.endPrefixMapping.assert_not_called()


class TestAttr(XMLTestCase):
    def test_rejects_required_kwarg(self):
        with self.assertRaises(TypeError):
            xso.Attr("foo", required=False)

    def test_default_defaults_to_no_default(self):
        prop = xso.Attr("foo")
        self.assertIs(prop.default, xso.NO_DEFAULT)

    def test_tag_attribute(self):
        prop = xso.Attr("foo")
        self.assertEqual(
            (None, "foo"),
            prop.tag
        )

        prop = xso.Attr((None, "foo"))
        self.assertEqual(
            (None, "foo"),
            prop.tag
        )

        prop = xso.Attr(("bar", "foo"))
        self.assertEqual(
            ("bar", "foo"),
            prop.tag
        )

    def test_from_value_and_type(self):
        instance = make_instance_mock()

        prop = xso.Attr("foo", type_=xso.Integer())
        self.assertTrue(prop.from_value(instance, "123"))

        self.assertDictEqual(
            {
                prop: 123,
            },
            instance._xso_contents
        )

    def test_missing_passes_if_defaulted(self):
        ctx = xso_model.Context()

        instance = make_instance_mock()

        default = object()
        prop = xso.Attr("foo", default=default)
        prop.handle_missing(instance, ctx)

        self.assertIs(prop.__get__(instance, type(instance)), default)

    def test_missing_raises_if_not_defaulted(self):
        ctx = xso_model.Context()

        instance = make_instance_mock()

        prop = xso.Attr("foo")
        with self.assertRaisesRegex(ValueError, "missing attribute foo"):
            prop.handle_missing(instance, ctx)

    def test_erroneous_as_absent_returns_False_from_from_value(self):
        ctx = xso_model.Context()

        instance = make_instance_mock()

        prop = xso.Attr(
            "foo",
            erroneous_as_absent=True,
            type_=xso.Integer(),
        )
        self.assertFalse(prop.from_value(instance, "xyz"))

    def test_to_dict(self):
        d = {}

        prop = xso.Attr("foo", type_=xso.Bool())
        instance = make_instance_mock({prop: True})

        prop.to_dict(instance, d)
        self.assertDictEqual(
            {
                (None, "foo"): "true"
            },
            d)

    def test_to_dict_unset_and_undefaulted_raises(self):
        prop = xso.Attr("foo")
        instance = make_instance_mock()

        with self.assertRaises(AttributeError):
            d = {}
            prop.to_dict(instance, d)

    def test_to_dict_defaulted(self):
        prop = xso.Attr("foo", default="bar")
        instance = make_instance_mock({prop: "bar"})

        d = {}
        prop.to_dict(instance, d)
        self.assertDictEqual(
            {
            },
            d)

    def test_validates(self):
        validator = unittest.mock.MagicMock()
        instance = make_instance_mock()

        prop = xso.Attr("foo", validator=validator)

        validator.validate.return_value = True
        prop.from_value(instance, "foo")

        validator.validate.return_value = False
        with self.assertRaises(ValueError):
            prop.from_value(instance, "foo")

        self.assertSequenceEqual(
            [
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("foo"),
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate("foo"),
            ],
            validator.mock_calls)

    def test_validator_ignores_default(self):
        validator = unittest.mock.MagicMock()
        instance = make_instance_mock()

        prop = xso.Attr("foo", validator=validator, default=None,
                        validate=xso_model.ValidateMode.ALWAYS)
        prop.__set__(instance, None)
        validator.validate.assert_not_called()

    def test_coerces(self):
        type_ = unittest.mock.MagicMock()
        instance = make_instance_mock()

        prop = xso.Attr("foo", type_=type_)
        prop.__set__(instance, "bar")

        type_.coerce.assert_called_once_with("bar")

    def test_missing(self):
        ctx = xso_model.Context()

        missing = unittest.mock.MagicMock()
        missing.return_value = "123"

        instance = make_instance_mock()

        prop = xso.Attr("foo", missing=missing)
        prop.handle_missing(instance, ctx)

        self.assertSequenceEqual(
            [
                unittest.mock.call(instance, ctx)
            ],
            missing.mock_calls
        )

        self.assertEqual(
            "123",
            prop.__get__(instance, type(instance))
        )

    def test_validate_contents_rejects_unset_and_undefaulted(self):
        instance = make_instance_mock()
        prop = xso.Attr("foo")

        with self.assertRaisesRegex(ValueError, "value required for"):
            prop.validate_contents(instance)

    def test_delete_reverts_to_default_if_available(self):
        class Cls(xso.XSO):
            prop = xso.Attr("foo", default="bar")

        obj = Cls()
        obj.prop = "foo"
        self.assertEqual(obj.prop, "foo")
        del obj.prop
        self.assertEqual(obj.prop, "bar")

    def test_delete_reverts_to_unset_if_default_not_available(self):
        class Cls(xso.XSO):
            prop = xso.Attr("foo")

        obj = Cls()
        obj.prop = "foo"
        self.assertEqual(obj.prop, "foo")
        del obj.prop
        with self.assertRaises(AttributeError):
            obj.prop


class TestChildValue(XMLTestCase):
    class DataXSO(xso_model.XSO):
        TAG = ("foo", "bar")

        value = xso_model.Text()

    def setUp(self):
        self.ctx = xso_model.Context()

    def tearDown(self):
        del self.ctx

    def test_init_imports_xso_types_from_type(self):
        xso_mock1 = unittest.mock.Mock(["TAG"])
        xso_mock2 = unittest.mock.Mock(["TAG"])

        type_ = unittest.mock.Mock(spec=xso_types.AbstractElementType)
        type_.get_xso_types.return_value = [xso_mock1, xso_mock2]

        prop = xso_model.ChildValue(type_)

        self.assertDictEqual(
            prop.get_tag_map(),
            {
                xso_mock1.TAG: xso_mock1,
                xso_mock2.TAG: xso_mock2,
            }
        )

    def test_from_events_uses_type_and_unpacks(self):
        type_ = unittest.mock.Mock([
            "get_xso_types",
            "unpack",
        ])

        type_.get_xso_types.return_value = [self.DataXSO]
        type_.unpack.return_value = unittest.mock.sentinel.unpacked

        subtree = etree.fromstring("<bar xmlns='foo'>value</bar>")

        instance = make_instance_mock()

        prop = xso_model.ChildValue(
            type_,
        )

        drive_from_events(prop.from_events, instance, subtree, self.ctx)

        self.assertDictEqual(
            {
                prop: unittest.mock.sentinel.unpacked
            },
            instance._xso_contents
        )

        type_.get_xso_types.assert_called_once_with()
        type_.unpack.assert_called_once_with(unittest.mock.ANY)

        _, (obj, ), _ = type_.unpack.mock_calls[0]

        self.assertIsInstance(obj, self.DataXSO)
        self.assertEqual(obj.value, "value")

    def test_to_sax_packs_value_and_saxifies_it(self):
        packed_xso = unittest.mock.Mock(["xso_serialise_to_sax"])

        type_mock = unittest.mock.Mock(["pack", "get_xso_types"])
        type_mock.get_xso_types.return_value = []
        type_mock.pack.return_value = packed_xso

        prop = xso_model.ChildValue(
            type_=type_mock
        )

        instance = make_instance_mock({
            prop: unittest.mock.sentinel.value
        })

        prop.to_sax(instance, unittest.mock.sentinel.dest)

        type_mock.pack.assert_called_once_with(unittest.mock.sentinel.value)
        packed_xso.xso_serialise_to_sax.assert_called_once_with(
            unittest.mock.sentinel.dest
        )

    def test_to_sax_complete(self):
        DataXSO = self.DataXSO

        class DataType(xso_types.AbstractElementType):
            def get_xso_types(self):
                return [DataXSO]

            def pack(self, v):
                result = DataXSO()
                result.value = v
                return result

            def unpack(self, o):
                return o.value

        class Wrapper(xso_model.XSO):
            TAG = ("foo", "foo")

            thing = xso_model.ChildValue(
                DataType(),
            )

        instance = Wrapper()
        instance.thing = "some value"

        parent = etree.Element("root")
        unparse_to_node(instance, parent)

        self.assertSubtreeEqual(
            etree.fromstring(
                "<root><foo xmlns='foo'><bar>some value</bar></foo></root>"
            ),
            parent,
        )


class TestChildText(XMLTestCase):
    def setUp(self):
        self.ctx = xso_model.Context()

    def test_init(self):
        type_mock = unittest.mock.MagicMock()
        validator_mock = unittest.mock.MagicMock()

        prop = xso.ChildText(
            tag="body",
            type_=type_mock,
            validator=validator_mock)
        self.assertEqual(
            (None, "body"),
            prop.tag)
        self.assertIs(
            type_mock,
            prop.type_)
        self.assertIs(
            validator_mock,
            prop.validator)
        self.assertIs(
            prop.default,
            xso.NO_DEFAULT
        )

    def test_from_events_with_type_and_validation(self):
        type_mock = unittest.mock.MagicMock()
        validator_mock = unittest.mock.MagicMock()

        instance = make_instance_mock()

        prop = xso.ChildText(
            "body",
            type_=type_mock,
            validator=validator_mock)

        subtree = etree.fromstring("<body>foo</body>")

        drive_from_events(prop.from_events, instance, subtree, self.ctx)

        type_mock.parse.assert_called_once_with("foo")

        self.assertDictEqual(
            {
                prop: type_mock.parse("foo"),
            },
            instance._xso_contents)
        self.assertSequenceEqual(
            [
                unittest.mock.call.__bool__(),
                unittest.mock.call.validate(type_mock.parse("foo")),
                unittest.mock.call.validate().__bool__(),
            ],
            validator_mock.mock_calls)
        self.assertSequenceEqual(
            [],
            instance.mock_calls)

    def test_from_events_validates(self):
        type_mock = unittest.mock.MagicMock()
        validator_mock = unittest.mock.MagicMock()

        instance = make_instance_mock()

        prop = xso.ChildText(
            "body",
            type_=type_mock,
            validator=validator_mock)

        subtree = etree.fromstring("<body>foo</body>")
        validator_mock.validate.return_value = False

        with self.assertRaises(ValueError):
            drive_from_events(prop.from_events, instance, subtree, self.ctx)

    def test_from_events_with_erroneous_as_absent(self):
        type_mock = unittest.mock.Mock()

        instance = make_instance_mock()

        prop = xso.ChildText(
            "body",
            type_=type_mock,
            erroneous_as_absent=True,
            default=unittest.mock.sentinel.default,
        )

        type_mock.parse.side_effect = ValueError()

        subtree = etree.fromstring("<body>foo</body>")
        drive_from_events(prop.from_events, instance, subtree, self.ctx)

        type_mock.parse.assert_called_once_with("foo")

        self.assertEqual(
            prop.__get__(instance, type(instance)),
            unittest.mock.sentinel.default,
        )

    def test_from_events_reraises_parse_errors_by_default(self):
        type_mock = unittest.mock.Mock()

        instance = make_instance_mock()

        prop = xso.ChildText(
            "body",
            type_=type_mock,
        )

        exc = ValueError()
        type_mock.parse.side_effect = exc

        subtree = etree.fromstring("<body>foo</body>")
        with self.assertRaises(ValueError) as ctx:
            drive_from_events(prop.from_events, instance, subtree, self.ctx)

        self.assertIs(ctx.exception, exc)

        type_mock.parse.assert_called_once_with("foo")

    def test_child_policy_default(self):
        prop = xso.ChildText("body")
        self.assertEqual(
            xso.UnknownChildPolicy.FAIL,
            prop.child_policy)

    def test_enforce_child_policy_fail(self):
        instance = make_instance_mock()

        prop = xso.ChildText(
            "body",
            child_policy=xso.UnknownChildPolicy.FAIL)
        subtree = etree.fromstring("<body>foo<bar/></body>")

        with self.assertRaises(ValueError):
            drive_from_events(prop.from_events, instance, subtree, self.ctx)

        self.assertFalse(instance._xso_contents)

    def test_enforce_child_policy_drop(self):
        instance = make_instance_mock()

        prop = xso.ChildText(
            "body",
            child_policy=xso.UnknownChildPolicy.DROP)
        subtree = etree.fromstring("<body>foo<bar/>bar</body>")
        drive_from_events(prop.from_events, instance, subtree, self.ctx)

        self.assertDictEqual(
            {
                prop: "foobar",
            },
            instance._xso_contents)

    def test_attr_policy_default(self):
        prop = xso.ChildText("body")
        self.assertEqual(
            xso.UnknownAttrPolicy.FAIL,
            prop.attr_policy)

    def test_enforce_attr_policy_fail(self):
        instance = make_instance_mock()

        prop = xso.ChildText(
            "body",
            attr_policy=xso.UnknownAttrPolicy.FAIL)
        subtree = etree.fromstring("<body a='bar'>foo</body>")

        with self.assertRaises(ValueError):
            drive_from_events(prop.from_events, instance, subtree, self.ctx)

        self.assertFalse(instance._xso_contents)

    def test_enforce_attr_policy_drop(self):
        instance = make_instance_mock()

        prop = xso.ChildText(
            "body",
            attr_policy=xso.UnknownAttrPolicy.DROP)
        subtree = etree.fromstring("<body a='bar'>foo</body>")

        drive_from_events(prop.from_events, instance, subtree, self.ctx)

        self.assertDictEqual(
            {
                prop: "foo",
            },
            instance._xso_contents)

    def test_to_sax(self):
        dest = unittest.mock.MagicMock()

        type_mock = unittest.mock.MagicMock()
        type_mock.format.return_value = "foo"

        prop = xso.ChildText(
            "body",
            type_=type_mock
        )

        instance = make_instance_mock({
            prop: "foo"
        })

        prop.to_sax(instance, dest)

        self.assertSequenceEqual(
            [
                unittest.mock.call.startElementNS((None, "body"), None, {}),
                unittest.mock.call.characters("foo"),
                unittest.mock.call.endElementNS((None, "body"), None)
            ],
            dest.mock_calls)
        self.assertSequenceEqual(
            [
                unittest.mock.call.format("foo"),
            ],
            type_mock.mock_calls)

    def test_to_sax_declare_prefix(self):
        prefix = object()
        dest = unittest.mock.MagicMock()

        type_mock = unittest.mock.MagicMock()
        type_mock.format.return_value = "foo"

        prop = xso.ChildText(
            ("uri:foo", "body"),
            type_=type_mock,
            declare_prefix=prefix
        )

        instance = make_instance_mock({
            prop: "foo"
        })

        prop.to_sax(instance, dest)

        self.assertSequenceEqual(
            [
                unittest.mock.call.startPrefixMapping(prefix, "uri:foo"),
                unittest.mock.call.startElementNS(
                    ("uri:foo", "body"),
                    None,
                    {}),
                unittest.mock.call.characters("foo"),
                unittest.mock.call.endElementNS(
                    ("uri:foo", "body"),
                    None),
                unittest.mock.call.endPrefixMapping(prefix)
            ],
            dest.mock_calls)
        self.assertSequenceEqual(
            [
                unittest.mock.call.format("foo"),
            ],
            type_mock.mock_calls)

    def test_to_sax_unset_raises(self):
        prop = xso.ChildText("body")

        instance = make_instance_mock()

        dest = unittest.mock.MagicMock()
        with self.assertRaises(AttributeError):
            prop.to_sax(instance, dest)

    def test_to_sax_defaulting(self):
        prop = xso.ChildText("body", default="foo")

        instance = make_instance_mock()

        dest = unittest.mock.MagicMock()
        prop.to_sax(instance, dest)
        self.assertSequenceEqual(
            [
            ],
            dest.mock_calls)

        instance._xso_contents = {prop: None}
        dest = unittest.mock.MagicMock()
        prop.to_sax(instance, dest)
        self.assertSequenceEqual(
            [
                unittest.mock.call.startElementNS((None, "body"), None, {}),
                unittest.mock.call.characters("None"),
                unittest.mock.call.endElementNS((None, "body"), None)
            ],
            dest.mock_calls)

        instance._xso_contents = {prop: ""}
        dest = unittest.mock.MagicMock()
        prop.to_sax(instance, dest)
        self.assertSequenceEqual(
            [
                unittest.mock.call.startElementNS((None, "body"), None, {}),
                unittest.mock.call.characters(""),
                unittest.mock.call.endElementNS((None, "body"), None)
            ],
            dest.mock_calls)

    def test_coerces(self):
        type_ = unittest.mock.MagicMock()
        instance = make_instance_mock()

        prop = xso.ChildText("body", type_=type_)
        prop.__set__(instance, "bar")

        type_.coerce.assert_called_once_with("bar")

    def test_validate_contents_rejects_unset_and_undefaulted(self):
        instance = make_instance_mock()

        prop = xso.ChildText("body")

        with self.assertRaises(ValueError):
            prop.validate_contents(instance)


class TestChildMap(XMLTestCase):
    def setUp(self):
        self.ctx = xso_model.Context()

    def test_class_access_returns_BoundDescriptor(self):
        prop = xso.ChildMap([])

        class Foo(xso.XSO):
            cm = prop

        with unittest.mock.patch(
                "aioxmpp.xso.query.BoundDescriptor") as BoundDescriptor:
            result = Foo.cm

        BoundDescriptor.assert_called_with(
            Foo,
            prop,
            xso_query.GetMappingDescriptor,
        )

        self.assertEqual(
            result,
            BoundDescriptor()
        )

    def test_from_events_from_init(self):
        class Bar(xso.XSO):
            TAG = "bar"

        class Foo(xso.XSO):
            TAG = "foo"

        instance = make_instance_mock()

        prop = xso.ChildMap([Foo, Bar])

        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<bar/>"),
            self.ctx
        )
        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<foo/>"),
            self.ctx
        )
        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<bar/>"),
            self.ctx
        )

        self.assertIn(prop, instance._xso_contents)
        resultmap = instance._xso_contents[prop]
        self.assertEqual(2, len(resultmap))
        self.assertIn(Bar.TAG, resultmap)
        self.assertIn(Foo.TAG, resultmap)

        bar_results = resultmap[Bar.TAG]
        self.assertEqual(2, len(bar_results))
        self.assertIsInstance(bar_results[0], Bar)
        self.assertIsInstance(bar_results[1], Bar)

        self.assertIsInstance(bar_results, xso_model.XSOList)

        foo_results = resultmap[Foo.TAG]
        self.assertEqual(1, len(foo_results))
        self.assertIsInstance(foo_results[0], Foo)

        self.assertIsInstance(foo_results, xso_model.XSOList)

    def test_assign_not_allowed(self):
        class Cls(xso.XSO):
            children = xso.ChildMap([])
        obj = Cls()

        with self.assertRaises(AttributeError):
            obj.children = 123
        with self.assertRaises(AttributeError):
            obj.children = "foo"
        d = {}
        with self.assertRaises(AttributeError):
            obj.children = d

    def test_lists_are_XSOList_instances(self):
        class Cls(xso.XSO):
            children = xso.ChildMap([])
        obj = Cls()

        self.assertIsInstance(obj.children["foo"], xso_model.XSOList)

    def test_to_node(self):
        # we run the test through to_node here, to avoid ordering issues with
        # the dict.

        class Bar(xso.XSO):
            TAG = "bar"

        class Foo(xso.XSO):
            TAG = "foo"

            attr = xso.Attr("a")

            def __init__(self, a=None):
                super().__init__()
                self.attr = a

        prop = xso.ChildMap([Foo, Bar])

        instance = make_instance_mock({
            prop: {
                Bar.TAG: [Bar()],
                Foo.TAG: [Foo(a="1"), Foo(a="2")]
            }
        })

        parent = etree.Element("root")
        prop.to_node(instance, parent)
        self.assertSubtreeEqual(
            etree.fromstring("<root><foo a='1'/><foo a='2'/><bar/></root>"),
            parent)

    def test_custom_key_function(self):
        class Bar(xso.XSO):
            TAG = "bar"

        class Foo(xso.XSO):
            TAG = "foo"

        instance = make_instance_mock()

        prop = xso.ChildMap(
            [Foo, Bar],
            key=lambda obj: obj.TAG[1]
        )

        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<bar/>"),
            self.ctx
        )
        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<foo/>"),
            self.ctx
        )
        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<bar/>"),
            self.ctx
        )

        self.assertIn(prop, instance._xso_contents)
        resultmap = instance._xso_contents[prop]
        self.assertEqual(2, len(resultmap))
        self.assertIn("bar", resultmap)
        self.assertIn("foo", resultmap)

        bar_results = resultmap["bar"]
        self.assertEqual(2, len(bar_results))
        self.assertIsInstance(bar_results[0], Bar)
        self.assertIsInstance(bar_results[1], Bar)

        foo_results = resultmap["foo"]
        self.assertEqual(1, len(foo_results))
        self.assertIsInstance(foo_results[0], Foo)

    def test_validate_contents_recurses_to_all_children(self):
        class Bar(xso.XSO):
            TAG = "bar"

        class Foo(xso.XSO):
            TAG = "foo"

        class Root(xso.XSO):
            TAG = "root"

            children = xso.ChildMap([Foo, Bar])

        root = Root()
        root.children[Foo].append(Foo())
        root.children[Foo].append(Foo())
        root.children[Bar].append(Bar())

        with contextlib.ExitStack() as stack:
            foo_validate = stack.enter_context(
                unittest.mock.patch.object(Foo, "validate")
            )
            bar_validate = stack.enter_context(
                unittest.mock.patch.object(Bar, "validate")
            )

            root.validate()

        self.assertSequenceEqual(
            [
                unittest.mock.call()
            ]*2,
            foo_validate.mock_calls
        )

        self.assertSequenceEqual(
            [
                unittest.mock.call()
            ],
            bar_validate.mock_calls
        )

    def test_fill_into_dict(self):
        class Bar(xso.XSO):
            TAG = "bar"

        class Foo(xso.XSO):
            TAG = "foo"

        instance = make_instance_mock()

        prop = xso.ChildMap([Foo, Bar])

        data = collections.defaultdict(lambda: [])
        instances = [Foo(), Bar(), Foo(), Foo(), Bar()]
        prop.fill_into_dict(instances, data)

        self.maxDiff = None
        self.assertDictEqual(
            data,
            {
                Foo.TAG: [instances[0], instances[2], instances[3]],
                Bar.TAG: [instances[1], instances[4]]
            }
        )


class TestChildLangMap(unittest.TestCase):
    def setUp(self):
        self.ctx = xso_model.Context()

    def test_inherits_from_child_map(self):
        self.assertIsInstance(
            xso.ChildLangMap([]),
            xso.ChildMap
        )

    def test_from_events_with_context(self):
        class Foo(xso.XSO):
            TAG = "foo"

            lang = xso.LangAttr()

        instance = make_instance_mock()

        prop = xso.ChildLangMap(
            [Foo]
        )

        en_GB = structs.LanguageTag.fromstr("en-gb")
        de_DE = structs.LanguageTag.fromstr("de-de")

        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<foo xml:lang='en-GB'/>"),
            self.ctx
        )

        self.ctx.lang = structs.LanguageTag.fromstr("en-gb")
        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<foo />"),
            self.ctx
        )
        self.ctx.lang = None

        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<foo xml:lang='de-de'/>"),
            self.ctx
        )

        self.assertIn(prop, instance._xso_contents)
        resultmap = instance._xso_contents[prop]
        self.assertEqual(2, len(resultmap))
        self.assertIn(en_GB, resultmap)
        self.assertIn(de_DE, resultmap)

        en_results = resultmap[en_GB]
        self.assertEqual(2, len(en_results))
        for result in en_results:
            self.assertEqual(en_GB, result.lang)

        de_results = resultmap[de_DE]
        self.assertEqual(1, len(de_results))
        for result in de_results:
            self.assertEqual(de_DE, result.lang)


class TestLangAttr(unittest.TestCase):
    def test_init(self):
        prop = xso.LangAttr()
        self.assertIsInstance(
            prop,
            xso.Attr)
        self.assertEqual(
            prop.tag,
            (namespaces.xml, "lang")
        )
        self.assertEqual(
            prop.missing,
            xso.lang_attr
        )
        self.assertIsInstance(
            prop.type_,
            xso.LanguageTag
        )
        self.assertIs(prop.default, None)


class TestChildTag(unittest.TestCase):
    def setUp(self):
        self.ctx = xso_model.Context()

    def test_allow_none_maps_to_default_and_vice_versa(self):
        prop = xso.ChildTag([], allow_none="foo")
        self.assertIs(prop.default, None)
        self.assertIs(prop.allow_none, True)

        prop = xso.ChildTag([], allow_none="")
        self.assertIs(prop.default, xso.NO_DEFAULT)
        self.assertIs(prop.allow_none, False)

    def test_allow_none_is_not_writable(self):
        prop = xso.ChildTag([], allow_none=False)
        with self.assertRaises(AttributeError):
            prop.allow_none = True

    def test_from_events(self):
        instance = make_instance_mock()

        prop = xso.ChildTag(
            tags=[
                "foo",
                "bar"
            ],
            default_ns="uri:foo")

        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<foo xmlns='uri:foo'/>"),
            self.ctx
        )

        self.assertDictEqual(
            {
                prop: ("uri:foo", "foo"),
            },
            instance._xso_contents
        )

    def test_child_policy_fail(self):
        instance = make_instance_mock()
        prop = xso.ChildTag(
            tags=[
                "foo",
                "bar"
            ],
            default_ns="uri:foo",
            child_policy=xso.UnknownChildPolicy.FAIL)

        with self.assertRaises(ValueError):
            drive_from_events(
                prop.from_events,
                instance,
                etree.fromstring("<foo xmlns='uri:foo'><bar/></foo>"),
                self.ctx
            )

        self.assertFalse(instance._xso_contents)

    def test_child_policy_drop(self):
        instance = make_instance_mock()
        prop = xso.ChildTag(
            tags=[
                "foo",
                "bar"
            ],
            default_ns="uri:foo",
            child_policy=xso.UnknownChildPolicy.DROP)

        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<foo xmlns='uri:foo'><bar/></foo>"),
            self.ctx
        )

        self.assertDictEqual(
            {
                prop: ("uri:foo", "foo"),
            },
            instance._xso_contents
        )

    def test_attr_policy_fail(self):
        instance = make_instance_mock()
        prop = xso.ChildTag(
            tags=[
                "foo",
                "bar"
            ],
            default_ns="uri:foo",
            attr_policy=xso.UnknownAttrPolicy.FAIL)

        with self.assertRaises(ValueError):
            drive_from_events(
                prop.from_events,
                instance,
                etree.fromstring("<foo a='b' xmlns='uri:foo'/>"),
                self.ctx
            )

        self.assertFalse(instance._xso_contents)

    def test_attr_policy_drop(self):
        instance = make_instance_mock()
        prop = xso.ChildTag(
            tags=[
                "foo",
                "bar"
            ],
            default_ns="uri:foo",
            attr_policy=xso.UnknownAttrPolicy.DROP)

        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<foo a='b' xmlns='uri:foo'/>"),
            self.ctx
        )

        self.assertDictEqual(
            {
                prop: ("uri:foo", "foo"),
            },
            instance._xso_contents
        )

    def test_text_policy_fail(self):
        instance = make_instance_mock()
        prop = xso.ChildTag(
            tags=[
                "foo",
                "bar"
            ],
            default_ns="uri:foo",
            text_policy=xso.UnknownTextPolicy.FAIL)

        with self.assertRaises(ValueError):
            drive_from_events(
                prop.from_events,
                instance,
                etree.fromstring("<foo xmlns='uri:foo'>bar</foo>"),
                self.ctx
            )

        self.assertFalse(instance._xso_contents)

    def test_text_policy_drop(self):
        instance = make_instance_mock()
        prop = xso.ChildTag(
            tags=[
                "foo",
                "bar"
            ],
            default_ns="uri:foo",
            text_policy=xso.UnknownTextPolicy.DROP)

        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<foo xmlns='uri:foo'>bar</foo>"),
            self.ctx
        )

        self.assertDictEqual(
            {
                prop: ("uri:foo", "foo"),
            },
            instance._xso_contents
        )

    def test_to_sax(self):
        prop = xso.ChildTag(
            tags=[
                "foo",
                "bar"
            ],
            default_ns="uri:foo")

        instance = make_instance_mock({
            prop: ("uri:foo", "bar")
        })

        dest = unittest.mock.MagicMock()
        prop.to_sax(instance, dest)

        self.assertSequenceEqual(
            [
                unittest.mock.call.startElementNS(
                    ("uri:foo", "bar"),
                    None,
                    {}),
                unittest.mock.call.endElementNS(
                    ("uri:foo", "bar"),
                    None)
            ],
            dest.mock_calls)

    def test_to_sax_declare_prefix(self):
        prefix = object()

        prop = xso.ChildTag(
            tags=[
                "foo",
                "bar"
            ],
            default_ns="uri:foo",
            declare_prefix=prefix)

        instance = make_instance_mock({
            prop: ("uri:foo", "bar")
        })

        dest = unittest.mock.MagicMock()
        prop.to_sax(instance, dest)

        self.assertSequenceEqual(
            [
                unittest.mock.call.startPrefixMapping(prefix, "uri:foo"),
                unittest.mock.call.startElementNS(
                    ("uri:foo", "bar"),
                    None,
                    {}),
                unittest.mock.call.endElementNS(
                    ("uri:foo", "bar"),
                    None),
                unittest.mock.call.endPrefixMapping(prefix),
            ],
            dest.mock_calls)

    def test_to_sax_declare_prefix_skips_if_namespaceless(self):
        prefix = object()

        prop = xso.ChildTag(
            tags=[
                "foo",
                "bar"
            ],
            declare_prefix=prefix)

        instance = make_instance_mock({
            prop: (None, "bar")
        })

        dest = unittest.mock.MagicMock()
        prop.to_sax(instance, dest)

        self.assertSequenceEqual(
            [
                unittest.mock.call.startElementNS(
                    (None, "bar"),
                    None,
                    {}),
                unittest.mock.call.endElementNS(
                    (None, "bar"),
                    None),
            ],
            dest.mock_calls)

    def test_validate_contents_rejects_unset_and_undefaulted(self):
        prop = xso.ChildTag(
            tags=[
                "foo",
                "bar"
            ])

        instance = make_instance_mock()

        with self.assertRaises(ValueError):
            prop.validate_contents(instance)

    def test_tag_enum_parse(self):
        instance = make_instance_mock()
        prop = xso.ChildTag(Tags)

        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<bar xmlns='urn:example:tags'/>"),
            self.ctx
        )

        self.assertDictEqual(
            {
                prop: Tags.BAR,
            },
            instance._xso_contents
        )

    def test_tag_enum_to_sax(self):
        prop = xso.ChildTag(Tags)
        instance = make_instance_mock({
            prop: Tags.FOO
        })
        dest = unittest.mock.MagicMock()
        prop.to_sax(instance, dest)
        self.assertSequenceEqual(
            dest.mock_calls,
            [
                unittest.mock.call.startElementNS(
                    ("urn:example:tags", "foo"),
                    None, {}),
                unittest.mock.call.endElementNS(
                    ("urn:example:tags", "foo"),
                    None),
            ]
        )


class TestChildFlag(unittest.TestCase):
    def setUp(self):
        self.ctx = xso_model.Context()

    def test_get_tag_map(self):
        self.assertSetEqual(
            xso.ChildFlag("foo").get_tag_map(),
            {(None, "foo")}
        )
        self.assertSetEqual(
            xso.ChildFlag(("uri:foo", "foo")).get_tag_map(),
            {("uri:foo", "foo")}
        )

    def test_from_events(self):
        instance = make_instance_mock()

        prop = xso.ChildFlag(
            tag=("uri:foo", "foo")
        )

        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<foo xmlns='uri:foo'/>"),
            self.ctx
        )

        self.assertDictEqual(
            {
                prop: True,
            },
            instance._xso_contents
        )

    def test_defaults_to_false(self):
        instance = make_instance_mock()

        prop = xso.ChildFlag(
            tag=("uri:foo", "foo")
        )

        self.assertFalse(prop.__get__(instance, type(instance)))

    def test_child_policy_fail(self):
        instance = make_instance_mock()
        prop = xso.ChildFlag(
            tag=("uri:foo", "foo"),
            child_policy=xso.UnknownChildPolicy.FAIL
        )

        with self.assertRaises(ValueError):
            drive_from_events(
                prop.from_events,
                instance,
                etree.fromstring("<foo xmlns='uri:foo'><bar/></foo>"),
                self.ctx
            )

        self.assertFalse(instance._xso_contents)

    def test_child_policy_drop(self):
        instance = make_instance_mock()
        prop = xso.ChildFlag(
            tag=("uri:foo", "foo"),
            child_policy=xso.UnknownChildPolicy.DROP
        )

        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<foo xmlns='uri:foo'><bar/></foo>"),
            self.ctx
        )

        self.assertDictEqual(
            {
                prop: True,
            },
            instance._xso_contents
        )

    def test_attr_policy_fail(self):
        instance = make_instance_mock()
        prop = xso.ChildFlag(
            tag=("uri:foo", "foo"),
            attr_policy=xso.UnknownAttrPolicy.FAIL
        )

        with self.assertRaises(ValueError):
            drive_from_events(
                prop.from_events,
                instance,
                etree.fromstring("<foo a='b' xmlns='uri:foo'/>"),
                self.ctx
            )

        self.assertFalse(instance._xso_contents)

    def test_attr_policy_drop(self):
        instance = make_instance_mock()
        prop = xso.ChildFlag(
            tag=("uri:foo", "foo"),
            attr_policy=xso.UnknownAttrPolicy.DROP
        )

        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<foo a='b' xmlns='uri:foo'/>"),
            self.ctx
        )

        self.assertDictEqual(
            {
                prop: True,
            },
            instance._xso_contents
        )

    def test_text_policy_fail(self):
        instance = make_instance_mock()
        prop = xso.ChildFlag(
            tag=("uri:foo", "foo"),
            text_policy=xso.UnknownTextPolicy.FAIL
        )

        with self.assertRaises(ValueError):
            drive_from_events(
                prop.from_events,
                instance,
                etree.fromstring("<foo xmlns='uri:foo'>bar</foo>"),
                self.ctx
            )

        self.assertFalse(instance._xso_contents)

    def test_text_policy_drop(self):
        instance = make_instance_mock()
        prop = xso.ChildFlag(
            tag=("uri:foo", "foo"),
            text_policy=xso.UnknownTextPolicy.DROP
        )

        drive_from_events(
            prop.from_events,
            instance,
            etree.fromstring("<foo xmlns='uri:foo'>bar</foo>"),
            self.ctx
        )

        self.assertDictEqual(
            {
                prop: True,
            },
            instance._xso_contents
        )

    def test_to_sax(self):
        prop = xso.ChildFlag(
            tag=("uri:foo", "foo"),
        )

        instance = make_instance_mock({
            prop: True,
        })

        dest = unittest.mock.MagicMock()
        prop.to_sax(instance, dest)

        self.assertSequenceEqual(
            [
                unittest.mock.call.startElementNS(
                    ("uri:foo", "foo"),
                    None,
                    {}),
                unittest.mock.call.endElementNS(
                    ("uri:foo", "foo"),
                    None)
            ],
            dest.mock_calls)

    def test_to_sax_declare_prefix(self):
        prop = xso.ChildFlag(
            tag=("uri:foo", "foo"),
            declare_prefix=unittest.mock.sentinel.prefix)

        instance = make_instance_mock({
            prop: True,
        })

        dest = unittest.mock.MagicMock()
        prop.to_sax(instance, dest)

        self.assertSequenceEqual(
            [
                unittest.mock.call.startPrefixMapping(
                    unittest.mock.sentinel.prefix,
                    "uri:foo"
                ),
                unittest.mock.call.startElementNS(
                    ("uri:foo", "foo"),
                    None,
                    {}),
                unittest.mock.call.endElementNS(
                    ("uri:foo", "foo"),
                    None),
                unittest.mock.call.endPrefixMapping(
                    unittest.mock.sentinel.prefix
                ),
            ],
            dest.mock_calls)

    def test_to_sax_declare_prefix_skips_if_namespaceless(self):
        prop = xso.ChildFlag(
            tag="foo",
            declare_prefix=unittest.mock.sentinel.prefix
        )

        instance = make_instance_mock({
            prop: (None, "bar")
        })

        dest = unittest.mock.MagicMock()
        prop.to_sax(instance, dest)

        self.assertSequenceEqual(
            [
                unittest.mock.call.startElementNS(
                    (None, "foo"),
                    None,
                    {}),
                unittest.mock.call.endElementNS(
                    (None, "foo"),
                    None),
            ],
            dest.mock_calls)


class Tags(enum.Enum):
    FOO = ("urn:example:tags", "foo")
    BAR = ("urn:example:tags", "bar")
    BAZ = ("urn:example:tags", "baz")


class FooWithNone(xso.XSO):
    tag_allows_none = xso.ChildTag(Tags, allow_none=True)


class Foo(xso.XSO):
    tag = xso.ChildTag(Tags)


class TestChildTagEnum(unittest.TestCase):
    def test_tag_enum_usage_normal(self):
        foo = Foo()
        foo.tag = Tags.FOO
        self.assertEqual(foo.tag, Tags.FOO)

        foo.tag = Tags.BAR
        self.assertEqual(foo.tag, Tags.BAR)

    def test_tag_enum_assign_none_allowed(self):
        foo = FooWithNone()
        foo.tag_allows_none = None
        self.assertIsNone(foo.tag_allows_none)

    def test_tag_enum_assign_none_raises(self):
        foo = Foo()
        with self.assertRaises(ValueError):
            foo.tag = None



class Testdrop_handler(unittest.TestCase):
    def test_drop_handler(self):
        result = object()

        def catch_result(value):
            nonlocal result
            result = value

        sd = xso.SAXDriver(
            functools.partial(contextless_from_wrapper,
                              xso_model.drop_handler),
            on_emit=catch_result)

        tree = etree.fromstring("<foo><bar a='fnord'/><baz>keks</baz></foo>")
        lxml.sax.saxify(tree, sd)

        self.assertIsNone(result)


class Testenforce_unknown_child_policy(unittest.TestCase):
    @unittest.mock.patch("aioxmpp.xso.model.drop_handler")
    def test_drop_policy(self, drop_handler):
        drop_handler.return_value = []
        gen = xso_model.enforce_unknown_child_policy(
            xso.UnknownChildPolicy.DROP,
            (None, "foo", {}))
        with self.assertRaises(StopIteration):
            next(gen)
        self.assertSequenceEqual(
            [
                unittest.mock.call((None, "foo", {})),
            ],
            drop_handler.mock_calls
        )

    def test_fail_policy(self):
        gen = xso_model.enforce_unknown_child_policy(
            xso.UnknownChildPolicy.FAIL,
            (None, "foo", {}))
        with self.assertRaises(ValueError):
            next(gen)

    @unittest.mock.patch("aioxmpp.xso.model.drop_handler")
    def test_fail_policy_can_be_suppressed_by_error_handler(
            self,
            drop_handler):
        drop_handler.return_value = []

        error_handler = unittest.mock.Mock()
        error_handler.return_value = True

        gen = xso_model.enforce_unknown_child_policy(
            xso.UnknownChildPolicy.FAIL,
            (None, "foo", {}),
            error_handler=error_handler)

        with self.assertRaises(StopIteration):
            next(gen)

        self.assertSequenceEqual(
            [
                unittest.mock.call(
                    None,
                    (None, "foo", {}),
                    None
                )
            ],
            error_handler.mock_calls
        )

        self.assertSequenceEqual(
            [
                unittest.mock.call((None, "foo", {})),
            ],
            drop_handler.mock_calls
        )


class Testguard(unittest.TestCase):
    def test_forward_to_argument_and_return_after_end(self):
        cmd_sequence = [
            ("start", None, "foo", {}),
            ("start", None, "bar", {}),
            ("text", "fnord"),
            ("end",),
            ("start", None, "bar", {}),
            ("text", "fnord"),
            ("end",),
            ("end",),
        ]

        dest = unittest.mock.MagicMock()
        guard = xso_model.guard(dest, cmd_sequence[0][1:])
        next(guard)

        for cmd in cmd_sequence[1:-1]:
            guard.send(cmd)

        value = object()
        dest.send.side_effect = StopIteration(value)

        with self.assertRaises(StopIteration) as ctx:
            guard.send(cmd_sequence[-1])

        self.assertSequenceEqual(
            [
                unittest.mock.call.__next__(),
            ]+[
                unittest.mock.call.send(cmd)
                for cmd in cmd_sequence[1:]
            ],
            dest.mock_calls
        )

        self.assertIs(
            ctx.exception.value,
            value
        )

    def test_return_only_after_end_even_on_exception_and_reraise(self):
        cmd_sequence = [
            ("start", None, "foo", {}),
            ("start", None, "bar", {}),
            ("text", "fnord"),
            ("end",),
            ("start", None, "bar", {}),
            ("text", "fnord"),
            ("end",),
            ("end",),
        ]

        dest = unittest.mock.MagicMock()
        guard = xso_model.guard(dest, cmd_sequence[0][1:])
        next(guard)

        for cmd in cmd_sequence[1:5]:
            guard.send(cmd)

        exc = ValueError()
        dest.send.side_effect = exc

        for cmd in cmd_sequence[5:-1]:
            guard.send(cmd)

        with self.assertRaises(ValueError) as ctx:
            guard.send(cmd_sequence[-1])

        self.assertSequenceEqual(
            [
                unittest.mock.call.__next__(),
            ]+[
                unittest.mock.call.send(cmd)
                for cmd in cmd_sequence[1:6]
            ],
            dest.mock_calls
        )

        self.assertIs(
            exc,
            ctx.exception
        )

    def test_eat_end_after_exception_on_start(self):
        class FooException(Exception):
            pass

        def processor():
            raise FooException()
            yield

        cmd_sequence = [
            ("start", None, "foo", {}),
            ("end",),
        ]

        dest = processor()
        guard = xso_model.guard(dest, cmd_sequence[0][1:])
        next(guard)

        with self.assertRaises(FooException):
            guard.send(cmd_sequence[1])

    def test_handles_increasing_nesting_while_dropping(self):
        cmd_sequence = [
            ("start", None, "foo", {}),
            ("start", None, "bar", {}),
            ("text", "fnord"),
            ("end",),
            ("start", None, "bar", {}),
            ("text", "fnord"),
            ("end",),
            ("end",),
        ]

        dest = unittest.mock.MagicMock()
        guard = xso_model.guard(dest, cmd_sequence[0][1:])
        next(guard)

        for cmd in cmd_sequence[1:2]:
            guard.send(cmd)

        exc = ValueError()
        dest.send.side_effect = exc

        for cmd in cmd_sequence[2:-1]:
            guard.send(cmd)

        with self.assertRaises(ValueError) as ctx:
            guard.send(cmd_sequence[-1])

        self.assertSequenceEqual(
            [
                unittest.mock.call.__next__(),
            ]+[
                unittest.mock.call.send(cmd)
                for cmd in cmd_sequence[1:3]
            ],
            dest.mock_calls
        )

        self.assertIs(
            exc,
            ctx.exception
        )
    def test_handles_increasing_nesting_while_after_error_during_start(self):
        class FooException(Exception):
            pass

        def processor():
            raise FooException()
            yield

        cmd_sequence = [
            ("start", None, "foo", {}),
            ("start", None, "bar", {}),
            ("text", "fnord"),
            ("end",),
            ("start", None, "bar", {}),
            ("text", "fnord"),
            ("end",),
            ("end",),
        ]

        dest = processor()
        guard = xso_model.guard(dest, cmd_sequence[0][1:])
        next(guard)

        for cmd in cmd_sequence[1:-1]:
            guard.send(cmd)

        with self.assertRaises(FooException):
            guard.send(cmd_sequence[-1])


class TestSAXDriver(unittest.TestCase):
    def setUp(self):
        self.l = []
        self.ctx = xso_model.Context()

    def catchall(self):
        while True:
            try:
                self.l.append((yield))
            except GeneratorExit as exc:
                self.l.append(exc)
                raise

    def test_forwards_startstop_events(self):
        tree = etree.fromstring("<foo/>")
        sd = xso.SAXDriver(self.catchall)
        lxml.sax.saxify(tree, sd)

        self.assertSequenceEqual(
            [
                ("start", None, "foo", {}),
                ("end",)
            ],
            self.l
        )

        sd.close()

    def test_forwards_text_events(self):
        tree = etree.fromstring("<foo>bar</foo>")
        sd = xso.SAXDriver(self.catchall)
        lxml.sax.saxify(tree, sd)

        self.assertSequenceEqual(
            [
                ("start", None, "foo", {}),
                ("text", "bar"),
                ("end",)
            ],
            self.l
        )

        sd.close()

    def test_forwards_nested_elements(self):
        tree = etree.fromstring("<foo><bar/></foo>")
        sd = xso.SAXDriver(self.catchall)
        lxml.sax.saxify(tree, sd)

        self.assertSequenceEqual(
            [
                ("start", None, "foo", {}),
                ("start", None, "bar", {}),
                ("end",),
                ("end",)
            ],
            self.l
        )

        sd.close()

    def test_forwards_attributes(self):
        tree = etree.fromstring("<foo><bar a='b'/></foo>")
        sd = xso.SAXDriver(self.catchall)
        lxml.sax.saxify(tree, sd)

        self.assertSequenceEqual(
            [
                ("start", None, "foo", {}),
                ("start", None, "bar", {(None, "a"): "b"}),
                ("end",),
                ("end",)
            ],
            self.l
        )

        sd.close()

    def test_forwards_namespaces(self):
        tree = etree.fromstring("<foo xmlns='uri:bar' />")
        sd = xso.SAXDriver(self.catchall)
        lxml.sax.saxify(tree, sd)

        self.assertSequenceEqual(
            [
                ("start", "uri:bar", "foo", {}),
                ("end",)
            ],
            self.l
        )

        sd.close()

    def test_collect_result(self):
        l = []
        results = []

        def returning_coroutine():
            nonlocal l
            while True:
                data = yield
                l.append(data)
                if data[0] == "end":
                    return "foo"

        def catch_result(value):
            nonlocal results
            results.append(value)

        tree = etree.fromstring("<foo/>")
        sd = xso.SAXDriver(
            returning_coroutine,
            on_emit=catch_result)
        lxml.sax.saxify(tree, sd)
        lxml.sax.saxify(tree, sd)

        self.assertSequenceEqual(
            [
                ("start", None, "foo", {}),
                ("end",),
            ]*2,
            l)
        self.assertSequenceEqual(
            ["foo"]*2,
            results)

        sd.close()

    def test_close_forwards_to_generator(self):
        sd = xso.SAXDriver(self.catchall)
        sd.startElementNS((None, "foo"), "foo", {})
        sd.close()

        self.assertIsInstance(self.l[-1], GeneratorExit)

    def tearDown(self):
        del self.l


class ChildTag(XMLTestCase):
    def setUp(self):
        self.prop = xso.ChildTag(
            [
                "foo",
                ("uri:foo", "bar"),
                "baz"
            ],
            default_ns="uri:bar")
        self.enum_prop = xso.ChildTag(
            Tags
        )
        self.ctx = xso_model.Context()

    def test_init(self):
        self.assertSetEqual(
            {
                ("uri:bar", "foo"),
                ("uri:foo", "bar"),
                ("uri:bar", "baz"),
            },
            self.prop.get_tag_map()
        )

    def test_valdiator(self):
        self.assertTrue(self.prop.validator.validate(("uri:bar", "foo")))
        self.assertFalse(self.prop.validator.validate(("uri:foo", "foo")))

    def test_converter(self):
        self.assertEqual(
            (None, "foo"),
            self.prop._converter.parse("foo")
        )
        self.assertEqual(
            "{uri:bar}foo",
            self.prop._converter.format(("uri:bar", "foo"))
        )

        self.assertEqual(
            Tags.FOO,
            self.enum_prop._converter.parse("{urn:example:tags}foo")
        )
        self.assertEqual(
            "{urn:example:tags}foo",
            self.enum_prop._converter.format(Tags.FOO)
        )

    def test_from_events(self):
        instance = make_instance_mock()

        drive_from_events(
            self.prop.from_events, instance,
            etree.fromstring("<foo xmlns='uri:bar'/>"),
            self.ctx
        )

        self.assertEqual(
            {
                self.prop: ("uri:bar", "foo"),
            },
            instance._xso_contents)

    def test_from_events_text_policy_fail(self):
        instance = make_instance_mock()
        self.prop.text_policy = xso.UnknownTextPolicy.FAIL

        with self.assertRaises(ValueError):
            drive_from_events(
                self.prop.from_events, instance,
                etree.fromstring("<foo xmlns='uri:bar'>text</foo>"),
                self.ctx
            )
        self.assertFalse(instance._xso_contents)

    def test_from_events_text_policy_drop(self):
        instance = make_instance_mock()
        self.prop.text_policy = xso.UnknownTextPolicy.DROP

        drive_from_events(
            self.prop.from_events, instance,
            etree.fromstring("<foo xmlns='uri:bar'>text</foo>"),
            self.ctx
        )

        self.assertEqual(
            {
                self.prop: ("uri:bar", "foo"),
            },
            instance._xso_contents)

    def test_from_events_child_policy_fail(self):
        instance = make_instance_mock()
        self.prop.child_policy = xso.UnknownChildPolicy.FAIL

        with self.assertRaises(ValueError):
            drive_from_events(
                self.prop.from_events, instance,
                etree.fromstring("<foo xmlns='uri:bar'><bar/></foo>"),
                self.ctx
            )
        self.assertFalse(instance._xso_contents)

    def test_from_events_child_policy_drop(self):
        instance = make_instance_mock()
        self.prop.child_policy = xso.UnknownChildPolicy.DROP

        drive_from_events(
            self.prop.from_events, instance,
            etree.fromstring("<foo xmlns='uri:bar'><bar/></foo>"),
            self.ctx
        )

        self.assertEqual(
            {
                self.prop: ("uri:bar", "foo"),
            },
            instance._xso_contents)

    def test_from_events_attr_policy_fail(self):
        instance = make_instance_mock()
        self.prop.attr_policy = xso.UnknownAttrPolicy.FAIL

        with self.assertRaises(ValueError):
            drive_from_events(
                self.prop.from_events, instance,
                etree.fromstring("<foo xmlns='uri:bar' a='bar'/>"),
                self.ctx
            )
        self.assertFalse(instance._xso_contents)

    def test_from_events_attr_policy_drop(self):
        instance = make_instance_mock()
        self.prop.attr_policy = xso.UnknownAttrPolicy.DROP

        drive_from_events(
            self.prop.from_events, instance,
            etree.fromstring("<foo xmlns='uri:bar' a='bar'/>"),
            self.ctx
        )

        self.assertEqual(
            {
                self.prop: ("uri:bar", "foo"),
            },
            instance._xso_contents)

    def test_to_sax(self):
        instance = make_instance_mock({
            self.prop: ("uri:bar", "foo")
        })

        dest = unittest.mock.MagicMock()
        self.prop.to_sax(instance, dest)
        self.assertSequenceEqual(
            [
                unittest.mock.call.startElementNS(
                    ("uri:bar", "foo"), None, {}),
                unittest.mock.call.endElementNS(
                    ("uri:bar", "foo"), None),
            ],
            dest.mock_calls)

    def test_to_sax_unset(self):
        instance = make_instance_mock({
            self.prop: None
        })

        dest = unittest.mock.MagicMock()
        self.prop.to_sax(instance, dest)
        self.assertSequenceEqual(
            [
            ],
            dest.mock_calls)

    def test_validate_from_code(self):
        class ClsWNone(xso.XSO):
            prop = xso.ChildTag(
                self.prop.get_tag_map(),
                allow_none=True)

        class ClsWONone(xso.XSO):
            prop = xso.ChildTag(
                self.prop.get_tag_map(),
                allow_none=False)

        w_none = ClsWNone()
        wo_none = ClsWONone()

        with self.assertRaises(ValueError):
            wo_none.prop = None
        with self.assertRaises(ValueError):
            wo_none.prop = ("foo", "bar")
        with self.assertRaises(ValueError):
            wo_none.prop = "foo"
        with self.assertRaises(ValueError):
            w_none.prop = ("foo", "bar")
        with self.assertRaises(ValueError):
            w_none.prop = "foo"

    def tearDown(self):
        del self.prop


class TestChildValueList(unittest.TestCase):
    class ChildXSO(xso.XSO):
        TAG = ("uri:foo", "foo")

        attr = xso.Attr("a", type_=xso.Integer())

    class ChildValueType(xso.AbstractElementType):
        @classmethod
        def get_xso_types(cls):
            return [TestChildValueList.ChildXSO]

        def pack(self, value):
            item = TestChildValueList.ChildXSO()
            item.attr = value
            return item

        def unpack(self, value):
            return value.attr

    def setUp(self):
        class Cls(xso.XSO):
            TAG = ("uri:foo", "p")

            values = xso_model.ChildValueList(self.ChildValueType)

        self.Cls = Cls

    def test_is_prop_base(self):
        self.assertTrue(issubclass(
            xso_model.ChildValueList,
            xso_model._ChildPropBase
        ))

    def test_get_tag_map_and_classes(self):
        self.assertDictEqual(
            {
                self.ChildXSO.TAG: self.ChildXSO
            },
            self.Cls.values.get_tag_map()
        )
        self.assertSetEqual(
            self.Cls.values._classes,
            {self.ChildXSO}
        )

    def test_registered_at_class_child_map(self):
        self.assertIn(
            self.ChildXSO.TAG,
            self.Cls.CHILD_MAP
        )
        self.assertIs(
            self.Cls.CHILD_MAP[self.ChildXSO.TAG],
            self.Cls.values.xq_descriptor
        )
        self.assertIn(
            self.Cls.values.xq_descriptor,
            self.Cls.CHILD_PROPS
        )

    def test_get_on_class_returns_BoundDescriptor(self):
        desc = xso_model.ChildValueList(self.ChildValueType)

        class Cls(xso.XSO):
            values = desc

        with unittest.mock.patch(
                "aioxmpp.xso.query.BoundDescriptor") as BoundDescriptor:
            result = Cls.values

        BoundDescriptor.assert_called_with(
            Cls,
            desc,
            xso_query.GetSequenceDescriptor,
            expr_kwargs={"sequence_factory": list}
        )

        self.assertEqual(
            result,
            BoundDescriptor()
        )

    def test_initial_value_is_a_mutable_sequence(self):
        obj = self.Cls()
        self.assertIsInstance(
            obj.values,
            collections.abc.MutableSequence)
        self.assertSequenceEqual(obj.values, [])

    def test_get_returns_per_instance_list(self):
        obj1 = self.Cls()
        obj2 = self.Cls()
        self.assertIs(obj1.values, obj1.values)
        self.assertIsNot(obj1.values, obj2.values)
        self.assertIs(obj2.values, obj2.values)

    def test_container_type_argument(self):
        mock = unittest.mock.Mock()

        class Cls(xso.XSO):
            TAG = ("uri:foo", "p")

            values = xso_model.ChildValueList(
                self.ChildValueType,
                container_type=mock
            )

        obj = Cls()
        container = obj.values
        self.assertEqual(container, mock())

    def test_container_type_not_called_if_attr_already_created(self):
        mock = unittest.mock.Mock()

        class Cls(xso.XSO):
            TAG = ("uri:foo", "p")

            values = xso_model.ChildValueList(
                self.ChildValueType,
                container_type=mock
            )

        obj = Cls()
        obj.values
        obj.values

        self.assertSequenceEqual(
            mock.mock_calls,
            [
                unittest.mock.call(),
            ]
        )

    def test_set_is_prohibited(self):
        obj = self.Cls()
        with self.assertRaises(AttributeError):
            obj.values = [1]

    def test_to_sax_calls_format(self):
        obj = self.Cls()
        obj.values.append(10)

        base = unittest.mock.Mock()

        with contextlib.ExitStack() as stack:
            stack.enter_context(unittest.mock.patch.object(
                self.ChildValueType,
                "pack",
                new=base.pack
            ))

            self.Cls.values.to_sax(obj, base.dest)

        self.assertSequenceEqual(
            base.mock_calls,
            [
                unittest.mock.call.pack(10),
                unittest.mock.call.pack().xso_serialise_to_sax(base.dest)
            ]
        )

    def test_from_events_uses__process_and_parse(self):
        obj = self.Cls()

        def process(mock, *args, **kwargs):
            return mock(*args, **kwargs)
            yield None

        base = unittest.mock.Mock()
        process_mock = base.process
        base.process = functools.partial(process, process_mock)

        with contextlib.ExitStack() as stack:
            stack.enter_context(unittest.mock.patch.object(
                self.ChildValueType,
                "unpack",
                new=base.unpack
            ))

            stack.enter_context(unittest.mock.patch.object(
                self.Cls.values.xq_descriptor,
                "_process",
                new=base.process
            ))

            with self.assertRaises(StopIteration):
                gen = self.Cls.values.from_events(
                    obj,
                    base.ev_args,
                    base.ctx,
                )
                next(gen)

            with self.assertRaises(StopIteration):
                gen = self.Cls.values.from_events(
                    obj,
                    base.ev_args,
                    base.ctx,
                )
                next(gen)

        calls = list(base.mock_calls)
        self.assertSequenceEqual(
            calls,
            [
                unittest.mock.call.process(obj, base.ev_args, base.ctx),
                unittest.mock.call.unpack(process_mock()),
                unittest.mock.call.process(obj, base.ev_args, base.ctx),
                unittest.mock.call.unpack(process_mock()),
            ]
        )

        self.assertSequenceEqual(
            obj.values,
            [
                base.unpack(),
                base.unpack(),
            ]
        )

    def test_from_events_works_with_set_container(self):
        class Cls(xso.XSO):
            TAG = ("uri:foo", "p")

            values = xso_model.ChildValueList(
                self.ChildValueType,
                container_type=set
            )

        obj = Cls()

        def process(mock, *args, **kwargs):
            return mock(*args, **kwargs)
            yield None

        base = unittest.mock.Mock()
        process_mock = base.process
        base.process = functools.partial(process, process_mock)

        with contextlib.ExitStack() as stack:
            stack.enter_context(unittest.mock.patch.object(
                self.ChildValueType,
                "unpack",
                new=base.unpack
            ))

            stack.enter_context(unittest.mock.patch.object(
                Cls.values.xq_descriptor,
                "_process",
                new=base.process
            ))

            base.unpack.return_value = 1
            with self.assertRaises(StopIteration):
                gen = Cls.values.from_events(
                    obj,
                    base.ev_args,
                    base.ctx,
                )
                next(gen)

            base.unpack.return_value = 2
            with self.assertRaises(StopIteration):
                gen = Cls.values.from_events(
                    obj,
                    base.ev_args,
                    base.ctx,
                )
                next(gen)

        calls = list(base.mock_calls)
        self.assertSequenceEqual(
            calls,
            [
                unittest.mock.call.process(obj, base.ev_args, base.ctx),
                unittest.mock.call.unpack(process_mock()),
                unittest.mock.call.process(obj, base.ev_args, base.ctx),
                unittest.mock.call.unpack(process_mock()),
            ]
        )

        self.assertSetEqual(
            obj.values,
            {
                1, 2
            }
        )

    def tearDown(self):
        del self.Cls


class TestChildValueMap(unittest.TestCase):
    class ChildXSO(xso.XSO):
        TAG = ("uri:foo", "foo")

        key = xso.Attr("k", type_=xso.Integer())
        value = xso.Attr("v", type_=xso.Integer())

    class ChildValueType(xso.AbstractElementType):
        @classmethod
        def get_xso_types(cls):
            return [TestChildValueMap.ChildXSO]

        def pack(self, item):
            key, value = item
            item = TestChildValueMap.ChildXSO()
            item.key = key
            item.value = value
            return item

        def unpack(self, item):
            return item.key, item.value

    def setUp(self):
        class Cls(xso.XSO):
            TAG = ("uri:foo", "p")

            values = xso_model.ChildValueMap(self.ChildValueType)

        self.Cls = Cls

    def test_is_child_prop_base(self):
        self.assertTrue(issubclass(
            xso_model.ChildValueMap,
            xso_model._ChildPropBase
        ))

    def test_get_tag_map_and_classes(self):
        self.assertDictEqual(
            self.Cls.values.get_tag_map(),
            {
                self.ChildXSO.TAG: self.ChildXSO,
            }
        )
        self.assertSetEqual(
            self.Cls.values._classes,
            {self.ChildXSO}
        )

    def test_registered_at_class_child_map(self):
        self.assertIn(
            self.ChildXSO.TAG,
            self.Cls.CHILD_MAP
        )
        self.assertIs(
            self.Cls.CHILD_MAP[self.ChildXSO.TAG],
            self.Cls.values.xq_descriptor
        )
        self.assertIn(
            self.Cls.values.xq_descriptor,
            self.Cls.CHILD_PROPS
        )

    def test_get_on_class_returns_descriptor(self):
        desc = xso_model.ChildValueMap(
            self.ChildValueType,
            mapping_type=unittest.mock.sentinel.mapping,
        )

        class Cls(xso.XSO):
            values = desc

        with unittest.mock.patch(
                "aioxmpp.xso.query.BoundDescriptor") as BoundDescriptor:
            result = Cls.values

        BoundDescriptor.assert_called_with(
            Cls,
            desc,
            xso_query.GetMappingDescriptor,
            expr_kwargs={
                "mapping_factory": unittest.mock.sentinel.mapping
            }
        )

        self.assertEqual(
            result,
            BoundDescriptor(),
        )

    def test_initial_value_is_a_mutable_mapping(self):
        obj = self.Cls()
        self.assertIsInstance(
            obj.values,
            collections.abc.MutableMapping)
        self.assertSequenceEqual(obj.values, {})

    def test_get_returns_per_instance_dict(self):
        obj1 = self.Cls()
        obj2 = self.Cls()
        self.assertIs(obj1.values, obj1.values)
        self.assertIsNot(obj1.values, obj2.values)
        self.assertIs(obj2.values, obj2.values)

    def test_mapping_type_argument(self):
        mock = unittest.mock.Mock()

        class Cls(xso.XSO):
            TAG = ("uri:foo", "p")

            values = xso_model.ChildValueMap(
                self.ChildValueType,
                mapping_type=mock
            )

        obj = Cls()
        mapping = obj.values
        self.assertEqual(mapping, mock())

    def test_mapping_type_not_called_if_attr_already_created(self):
        mock = unittest.mock.Mock()

        class Cls(xso.XSO):
            TAG = ("uri:foo", "p")

            values = xso_model.ChildValueMap(
                self.ChildValueType,
                mapping_type=mock
            )

        obj = Cls()
        obj.values
        obj.values

        self.assertSequenceEqual(
            mock.mock_calls,
            [
                unittest.mock.call(),
            ]
        )

    def test_set_is_prohibited(self):
        obj = self.Cls()
        with self.assertRaises(AttributeError):
            obj.values = {}

    def test_to_sax_calls_format(self):
        obj = self.Cls()
        obj.values[10] = 20

        base = unittest.mock.Mock()

        with contextlib.ExitStack() as stack:
            stack.enter_context(unittest.mock.patch.object(
                self.ChildValueType,
                "pack",
                new=base.pack
            ))

            self.Cls.values.to_sax(obj, base.dest)

        self.assertSequenceEqual(
            base.mock_calls,
            [
                unittest.mock.call.pack((10, 20)),
                unittest.mock.call.pack().xso_serialise_to_sax(base.dest)
            ]
        )

    def test_from_events_uses__process_and_parse(self):
        obj = self.Cls()

        def process(mock, *args, **kwargs):
            return mock(*args, **kwargs)
            yield None

        base = unittest.mock.Mock()
        process_mock = base.process
        base.process = functools.partial(process, process_mock)

        with contextlib.ExitStack() as stack:
            stack.enter_context(unittest.mock.patch.object(
                self.ChildValueType,
                "unpack",
                new=base.unpack
            ))

            stack.enter_context(unittest.mock.patch.object(
                self.Cls.values.xq_descriptor,
                "_process",
                new=base.process
            ))

            base.unpack.return_value = (1, "a")
            with self.assertRaises(StopIteration):
                gen = self.Cls.values.from_events(
                    obj,
                    base.ev_args,
                    base.ctx,
                )
                next(gen)

            base.unpack.return_value = (2, "b")
            with self.assertRaises(StopIteration):
                gen = self.Cls.values.from_events(
                    obj,
                    base.ev_args,
                    base.ctx,
                )
                next(gen)

        calls = list(base.mock_calls)
        self.assertSequenceEqual(
            calls,
            [
                unittest.mock.call.process(obj, base.ev_args, base.ctx),
                unittest.mock.call.unpack(process_mock()),
                unittest.mock.call.process(obj, base.ev_args, base.ctx),
                unittest.mock.call.unpack(process_mock()),
            ]
        )

        self.assertDictEqual(
            obj.values,
            {
                1: "a",
                2: "b"
            }
        )

    def tearDown(self):
        del self.Cls


class TestChildValueMultiMap(unittest.TestCase):
    class ChildXSO(xso.XSO):
        TAG = ("uri:foo", "foo")

        key = xso.Attr("k", type_=xso.Integer())
        value = xso.Attr("v", type_=xso.Integer())

    class ChildValueType(xso.AbstractElementType):
        @classmethod
        def get_xso_types(self):
            return [TestChildValueMultiMap.ChildXSO]

        def pack(self, item):
            key, value = item
            item = TestChildValueMultiMap.ChildXSO()
            item.key = key
            item.value = value
            return item

        def unpack(self, item):
            return item.key, item.value

    def setUp(self):
        class Cls(xso.XSO):
            TAG = ("uri:foo", "p")

            values = xso_model.ChildValueMultiMap(
                self.ChildValueType
            )

        self.Cls = Cls

    def test_is_child_prop_base(self):
        self.assertTrue(issubclass(
            xso_model.ChildValueMultiMap,
            xso_model._ChildPropBase
        ))

    def test_get_tag_map_and_classes(self):
        self.assertDictEqual(
            self.Cls.values.get_tag_map(),
            {
                self.ChildXSO.TAG: self.ChildXSO,
            }
        )
        self.assertSetEqual(
            self.Cls.values._classes,
            {self.ChildXSO}
        )

    def test_registered_at_class_child_map(self):
        self.assertIn(
            self.ChildXSO.TAG,
            self.Cls.CHILD_MAP
        )
        self.assertIs(
            self.Cls.CHILD_MAP[self.ChildXSO.TAG],
            self.Cls.values.xq_descriptor
        )
        self.assertIn(
            self.Cls.values.xq_descriptor,
            self.Cls.CHILD_PROPS
        )

    def test_get_on_class_returns_descriptor(self):
        desc = xso_model.ChildValueMultiMap(
            self.ChildValueType,
            mapping_type=unittest.mock.sentinel.mapping
        )

        class Cls(xso.XSO):
            values = desc

        with unittest.mock.patch(
                "aioxmpp.xso.query.BoundDescriptor") as BoundDescriptor:
            result = Cls.values

        BoundDescriptor.assert_called_with(
            Cls,
            desc,
            xso_query.GetMappingDescriptor,
            expr_kwargs={"mapping_factory": unittest.mock.sentinel.mapping}
        )

        self.assertEqual(
            result,
            BoundDescriptor(),
        )

    def test_initial_value_is_a_mutable_mapping(self):
        obj = self.Cls()
        self.assertIsInstance(
            obj.values,
            multidict.MultiDict)
        self.assertEqual(obj.values, {})

    def test_mapping_type(self):
        class Cls(xso.XSO):
            TAG = ("uri:foo", "p")

            values = xso_model.ChildValueMultiMap(
                self.ChildValueType,
                mapping_type=multidict.CIMultiDict
            )

        obj = Cls()
        self.assertIsInstance(
            obj.values,
            multidict.CIMultiDict)
        self.assertEqual(obj.values, {})

    def test_not_settable(self):
        obj = self.Cls()

        with self.assertRaises(AttributeError):
            obj.values = {}

    def test_from_events_uses__process_and_parse(self):
        obj = self.Cls()

        def process(mock, *args, **kwargs):
            return mock(*args, **kwargs)
            yield None

        base = unittest.mock.Mock()
        process_mock = base.process
        base.process = functools.partial(process, process_mock)

        with contextlib.ExitStack() as stack:
            stack.enter_context(unittest.mock.patch.object(
                self.ChildValueType,
                "unpack",
                new=base.unpack
            ))

            stack.enter_context(unittest.mock.patch.object(
                self.Cls.values.xq_descriptor,
                "_process",
                new=base.process
            ))

            base.unpack.return_value = ("x", "a")
            with self.assertRaises(StopIteration):
                gen = self.Cls.values.from_events(
                    obj,
                    base.ev_args,
                    base.ctx,
                )
                next(gen)

            base.unpack.return_value = ("x", "b")
            with self.assertRaises(StopIteration):
                gen = self.Cls.values.from_events(
                    obj,
                    base.ev_args,
                    base.ctx,
                )
                next(gen)

            base.unpack.return_value = ("z", "c")
            with self.assertRaises(StopIteration):
                gen = self.Cls.values.from_events(
                    obj,
                    base.ev_args,
                    base.ctx,
                )
                next(gen)

        calls = list(base.mock_calls)
        self.assertSequenceEqual(
            calls,
            [
                unittest.mock.call.process(obj, base.ev_args, base.ctx),
                unittest.mock.call.unpack(process_mock()),
                unittest.mock.call.process(obj, base.ev_args, base.ctx),
                unittest.mock.call.unpack(process_mock()),
                unittest.mock.call.process(obj, base.ev_args, base.ctx),
                unittest.mock.call.unpack(process_mock()),
            ]
        )

        self.assertEqual(
            obj.values,
            multidict.MultiDict([
                ("x", "a"),
                ("x", "b"),
                ("z", "c"),
            ])
        )

    def test_to_sax_calls_format(self):
        obj = self.Cls()
        obj.values.add("x", "foo")
        obj.values.add("x", "bar")
        obj.values.add("z", "baz")

        base = unittest.mock.Mock()

        with contextlib.ExitStack() as stack:
            stack.enter_context(unittest.mock.patch.object(
                self.ChildValueType,
                "pack",
                new=base.pack
            ))

            self.Cls.values.to_sax(obj, base.dest)

        self.assertSequenceEqual(
            base.mock_calls,
            [
                unittest.mock.call.pack(("x", "foo")),
                unittest.mock.call.pack().xso_serialise_to_sax(base.dest),
                unittest.mock.call.pack(("x", "bar")),
                unittest.mock.call.pack().xso_serialise_to_sax(base.dest),
                unittest.mock.call.pack(("z", "baz")),
                unittest.mock.call.pack().xso_serialise_to_sax(base.dest),
            ]
        )

    def tearDown(self):
        del self.Cls


class TestChildTextMap(unittest.TestCase):
    def test_init_cls(self):
        with contextlib.ExitStack() as stack:
            cvm = stack.enter_context(unittest.mock.patch.object(
                xso_model.ChildValueMap,
                "__init__",
            ))

            tcm = stack.enter_context(unittest.mock.patch(
                "aioxmpp.xso.types.TextChildMap",
            ))

            xso_ = unittest.mock.Mock(spec=xso_model.XMLStreamClass)

            obj = xso_model.ChildTextMap(xso_)

        self.assertSequenceEqual(
            list(tcm.mock_calls),
            [
                unittest.mock.call(xso_),
            ]
        )

        self.assertSequenceEqual(
            list(cvm.mock_calls),
            [unittest.mock.call(
                tcm(),
                mapping_type=structs.LanguageMap,
            ),
            ]
        )

        self.assertIsInstance(
            obj,
            xso_model.ChildTextMap
        )

    def test_init_tag(self):
        with contextlib.ExitStack() as stack:
            cvm = stack.enter_context(unittest.mock.patch.object(
                xso_model.ChildValueMap,
                "__init__",
            ))

            tcm = stack.enter_context(unittest.mock.patch(
                "aioxmpp.xso.types.TextChildMap",
            ))

            obj = xso_model.ChildTextMap(("foo", "bar"))

        self.assertSequenceEqual(
            tcm.mock_calls,
            [
                unittest.mock.call(unittest.mock.ANY),
            ]
        )

        (_, (xso_,), _), = tcm.mock_calls

        self.assertTrue(
            issubclass(xso_,
                       xso_model.AbstractTextChild)
        )

        self.assertEqual(xso_.TAG, ("foo", "bar"))

        self.assertSequenceEqual(
            list(cvm.mock_calls),
            [unittest.mock.call(
                tcm(),
                mapping_type=structs.LanguageMap,
            ),
            ]
        )

        self.assertIsInstance(
            obj,
            xso_model.ChildTextMap
        )


class TestXSOParser(XMLTestCase):
    def run_parser(self, classes, tree):
        results = []

        def catch_result(value):
            nonlocal results
            results.append(value)

        def fail_hard(*args):
            raise AssertionError("this should not be reached")

        parser = xso.XSOParser()
        for cls in classes:
            parser.add_class(cls, catch_result)

        sd = xso.SAXDriver(
            parser,
            on_emit=fail_hard
        )
        lxml.sax.saxify(tree, sd)

        return results

    def run_parser_one(self, stanza_cls, tree):
        results = self.run_parser(stanza_cls, tree)
        self.assertEqual(1, len(results))
        return results[0]

    def test_parse_text(self):
        class TestStanza(xso.XSO):
            TAG = "uri:bar", "foo"
            contents = xso.Text()
        tree = etree.fromstring("<foo xmlns='uri:bar'>bar</foo>")
        result = self.run_parser_one([TestStanza], tree)
        self.assertIsInstance(result, TestStanza)
        self.assertEqual(result.contents, "bar")

    def test_parse_text_split_in_multiple_events(self):
        class Dummy(xso.XSO):
            TAG = "uri:bar", "dummy"

        class TestStanza(xso.XSO):
            TAG = "uri:bar", "foo"

            contents = xso.Text()
            _ = xso.Child([Dummy])

        tree = etree.fromstring("<foo xmlns='uri:bar'>bar<dummy/>baz</foo>")
        result = self.run_parser_one([TestStanza], tree)
        self.assertIsInstance(result, TestStanza)
        self.assertEqual(result.contents, "barbaz")

    def test_handle_unknown_tag_at_toplevel(self):
        tree = etree.fromstring("<foo />")

        class TestStanza(xso.XSO):
            TAG = "uri:bar", "foo"

        with self.assertRaises(xso.UnknownTopLevelTag) as ctx:
            self.run_parser_one([TestStanza], tree)
        self.assertIsInstance(ctx.exception, ValueError)
        self.assertSequenceEqual(
            (None, "foo", {}),
            ctx.exception.ev_args
        )

    def test_handle_unknown_tag_at_non_toplevel(self):
        tree = etree.fromstring("<foo><bar/></foo>")

        class TestStanza(xso.XSO):
            TAG = None, "foo"

            UNKNOWN_CHILD_POLICY = xso.UnknownAttrPolicy.FAIL

        with self.assertRaises(ValueError):
            self.run_parser_one([TestStanza], tree)

    def test_handle_unknown_tag_at_non_toplevel_with_drop_policy(self):
        tree = etree.fromstring("<foo><bar/></foo>")

        class TestStanza(xso.XSO):
            TAG = None, "foo"
            UNKNOWN_CHILD_POLICY = xso.UnknownChildPolicy.DROP

        self.run_parser_one([TestStanza], tree)

    def test_parse_using_collector(self):
        tree = etree.fromstring("<foo><bar/></foo>")

        class TestStanza(xso.XSO):
            TAG = None, "foo"
            coll = xso.Collector()

        result = self.run_parser_one([TestStanza], tree)
        self.assertEqual(1, len(result.coll))
        self.assertSubtreeEqual(
            etree.fromstring("<bar/>"),
            result.coll[0])

    def test_handle_unknown_attribute(self):
        tree = etree.fromstring("<foo a='bar' />")

        class TestStanza(xso.XSO):
            TAG = None, "foo"

            UNKNOWN_ATTR_POLICY = xso.UnknownAttrPolicy.FAIL

        with self.assertRaises(ValueError):
            self.run_parser_one([TestStanza], tree)

    def test_handle_unknown_attribute_with_drop_policy(self):
        tree = etree.fromstring("<foo a='bar' />")

        class TestStanza(xso.XSO):
            TAG = None, "foo"
            UNKNOWN_ATTR_POLICY = xso.UnknownAttrPolicy.DROP

        self.run_parser_one([TestStanza], tree)

    def test_handle_unknown_text(self):
        tree = etree.fromstring("<foo>bar</foo>")

        class TestStanza(xso.XSO):
            TAG = None, "foo"

        with self.assertRaises(ValueError):
            self.run_parser_one([TestStanza], tree)

    def test_handle_missing_attribute(self):
        tree = etree.fromstring("<foo/>")

        class TestStanza(xso.XSO):
            TAG = None, "foo"
            attr = xso.Attr("a")

        with self.assertRaises(ValueError):
            self.run_parser_one([TestStanza], tree)

    def test_parse_simple_with_another_attribute(self):
        class TestStanza(xso.XSO):
            TAG = "uri:bar", "foo"
            text = xso.Text()

        tree = etree.fromstring("<foo xmlns='uri:bar'>bar</foo>")
        result = self.run_parser_one([TestStanza], tree)
        self.assertIsInstance(result, TestStanza)
        self.assertEqual(result.text, "bar")

    def test_parse_detect_class(self):
        class TestStanzaA(xso.XSO):
            TAG = "uri:bar", "a"

        class TestStanzaB(xso.XSO):
            TAG = "uri:bar", "b"

        tree = etree.fromstring("<a xmlns='uri:bar' />")
        result = self.run_parser_one([TestStanzaA, TestStanzaB], tree)
        self.assertIsInstance(result, TestStanzaA)

        tree = etree.fromstring("<b xmlns='uri:bar' />")
        result = self.run_parser_one([TestStanzaA, TestStanzaB], tree)
        self.assertIsInstance(result, TestStanzaB)

    def test_parse_child(self):
        class Bar(xso.XSO):
            TAG = "bar"

        class Foo(xso.XSO):
            TAG = "foo"

            child = xso.Child([Bar])

        tree = etree.fromstring("<foo><bar/></foo>")
        result = self.run_parser_one([Foo], tree)
        self.assertIsInstance(result, Foo)
        self.assertIsInstance(result.child, Bar)

    def test_parse_attribute(self):
        class Foo(xso.XSO):
            TAG = "foo"

            attr = xso.Attr("bar")

        tree = etree.fromstring("<foo bar='baz'/>")
        result = self.run_parser_one([Foo], tree)
        self.assertEqual(
            "baz",
            result.attr)

    def test_parse_attribute_nested(self):
        class Bar(xso.XSO):
            TAG = "bar"

            attr = xso.Attr("a")

        class Foo(xso.XSO):
            TAG = "foo"

            attr = xso.Attr("a")
            child = xso.Child([Bar])

        tree = etree.fromstring("<foo a='baz'><bar a='fnord'/></foo>")
        result = self.run_parser_one([Foo], tree)
        self.assertEqual(
            "baz",
            result.attr)
        self.assertEqual(
            "fnord",
            result.child.attr)

    def test_parse_child_flag(self):
        class Foo(xso.XSO):
            TAG = "foo"

            required = xso.ChildFlag(
                tag=("uri:foo", "required"),
            )

        tree = etree.fromstring(
            "<foo a='baz'><required xmlns='uri:foo'/></foo>"
        )
        result = self.run_parser_one([Foo], tree)
        self.assertTrue(result.required)

    def test_parse_child_list(self):
        class ClsLeafA(xso.XSO):
            TAG = "bar"

            attr = xso.Attr("a")

        class ClsLeafB(xso.XSO):
            TAG = "baz"

            attr = xso.Attr("b")

        class Foo(xso.XSO):
            TAG = "foo"

            cl = xso.ChildList([ClsLeafA, ClsLeafB])

        tree = etree.fromstring(
            "<foo>"
            "<bar a='1'/>"
            "<baz b='2'/>"
            "<bar a='3'/>"
            "<bar a='4'/>"
            "</foo>")
        result = self.run_parser_one([Foo], tree)
        self.assertEqual(4, len(result.cl))

        expected = [
            (ClsLeafA, "1"),
            (ClsLeafB, "2"),
            (ClsLeafA, "3"),
            (ClsLeafA, "4"),
        ]

        for i, (child, (cls, value)) in enumerate(zip(result.cl, expected)):
            self.assertIsInstance(child, cls, "child {}".format(i))
            self.assertEqual(child.attr, value, "child {}".format(i))

    def test_parse_child_with_post_register(self):
        class Foo(xso.XSO):
            TAG = "foo"

            child = xso.Child([])

        class Bar(xso.XSO):
            TAG = "bar"

        Foo.register_child(Foo.child, Bar)

        tree = etree.fromstring("<foo><bar/></foo>")
        result = self.run_parser_one([Foo], tree)

        self.assertIsInstance(result.child, Bar)

    def test_parse_child_text(self):
        class Foo(xso.XSO):
            TAG = "foo"
            body = xso.ChildText("body")

        tree = etree.fromstring("<foo><body>foobar</body></foo>")
        result = self.run_parser_one([Foo], tree)

        self.assertEqual(
            "foobar",
            result.body)

    def test_parse_ignore_whitespace_if_no_text_descriptor(self):
        class Foo(xso.XSO):
            TAG = "foo"
            body = xso.ChildText("body")

        tree = etree.fromstring("<foo>  \n<body>foobar</body>  </foo>")
        result = self.run_parser_one([Foo], tree)

        self.assertEqual(
            "foobar",
            result.body)

    def test_add_class(self):
        class Foo(xso.XSO):
            TAG = "foo"

        class Bar(xso.XSO):
            TAG = "bar"

        cb1, cb2 = object(), object()

        p = xso.XSOParser()
        p.add_class(Foo, cb1)
        p.add_class(Bar, cb2)

        self.assertDictEqual(
            {
                Foo.TAG: (Foo, cb1),
                Bar.TAG: (Bar, cb2)
            },
            p.get_tag_map()
        )

        self.assertDictEqual(
            {
                Foo: cb1,
                Bar: cb2
            },
            p.get_class_map()
        )

    def test_add_class_forbid_duplicate_tags(self):
        class Foo(xso.XSO):
            TAG = "foo"

        class Bar(xso.XSO):
            TAG = "foo"

        p = xso.XSOParser()
        p.add_class(Foo, None)
        with self.assertRaises(ValueError):
            p.add_class(Bar, None)

    def test_remove_class(self):
        class Foo(xso.XSO):
            TAG = "foo"

        class Bar(xso.XSO):
            TAG = "bar"

        p = xso.XSOParser()
        p.add_class(Foo, None)
        p.add_class(Bar, None)

        p.remove_class(Bar)
        self.assertDictEqual(
            {
                Foo.TAG: (Foo, None),
            },
            p.get_tag_map()
        )
        p.remove_class(Foo)
        self.assertFalse(p.get_tag_map())

    def test_ignore_toplevel_whitespace(self):
        class Foo(xso.XSO):
            TAG = "foo"

        cb = unittest.mock.Mock()

        p = xso.XSOParser()
        suspendable = p()
        next(suspendable)
        suspendable.send(("text", "\n\t "))

        p.add_class(Foo, cb)

        suspendable.send(("start", None, "foo", {}))
        suspendable.send(("end", None, "foo"))

        self.assertSequenceEqual(
            [
                unittest.mock.call(unittest.mock.ANY)
            ],
            cb.mock_calls
        )

    def test_lang_propagation_into_context(self):
        class Foo(xso.XSO):
            TAG = "foo"

            attr = xso.LangAttr()

        results = []

        def catch_result(value):
            nonlocal results
            results.append(value)

        def fail_hard(*args):
            raise AssertionError("this should not be reached")

        parser = xso.XSOParser()
        parser.add_class(Foo, catch_result)
        parser.lang = structs.LanguageTag.fromstr("de")

        tree = etree.fromstring("<foo/>")
        sd = xso.SAXDriver(
            parser,
            on_emit=fail_hard
        )
        lxml.sax.saxify(tree, sd)

        result, = results
        self.assertEqual(
            structs.LanguageTag.fromstr("de"),
            result.attr
        )

    def test_lang_propagation_if_changed_later(self):
        class Foo(xso.XSO):
            TAG = "foo"

            attr = xso.LangAttr()

        results = []

        def catch_result(value):
            nonlocal results
            results.append(value)

        def fail_hard(*args):
            raise AssertionError("this should not be reached")

        parser = xso.XSOParser()
        parser.add_class(Foo, catch_result)
        parser.lang = structs.LanguageTag.fromstr("de")

        tree = etree.fromstring("<foo/>")
        sd = xso.SAXDriver(
            parser,
            on_emit=fail_hard
        )
        lxml.sax.saxify(tree, sd)

        result, = results
        results.clear()
        self.assertEqual(
            structs.LanguageTag.fromstr("de"),
            result.attr
        )

        parser.lang = structs.LanguageTag.fromstr("en")

        tree = etree.fromstring("<foo/>")
        sd = xso.SAXDriver(
            parser,
            on_emit=fail_hard
        )
        lxml.sax.saxify(tree, sd)

        result, = results
        results.clear()
        self.assertEqual(
            structs.LanguageTag.fromstr("en"),
            result.attr
        )

    def test_local_lang_still_wins(self):
        class Foo(xso.XSO):
            TAG = "foo"

            attr = xso.LangAttr()

        results = []

        def catch_result(value):
            nonlocal results
            results.append(value)

        def fail_hard(*args):
            raise AssertionError("this should not be reached")

        parser = xso.XSOParser()
        parser.add_class(Foo, catch_result)
        parser.lang = structs.LanguageTag.fromstr("de")

        tree = etree.fromstring("<foo xml:lang='en'/>")
        sd = xso.SAXDriver(
            parser,
            on_emit=fail_hard
        )
        lxml.sax.saxify(tree, sd)

        result, = results
        results.clear()
        self.assertEqual(
            structs.LanguageTag.fromstr("en"),
            result.attr
        )


class TestContext(unittest.TestCase):
    def setUp(self):
        self.ctx = xso_model.Context()

    def test_init(self):
        self.assertIsNone(self.ctx.lang)

    def test_context_manager(self):
        self.ctx.lang = "foo"
        self.ctx.random_attribute = "fnord"
        with self.ctx as new_ctx:
            self.assertEqual("foo", new_ctx.lang)
            self.assertEqual("fnord", new_ctx.random_attribute)

            new_ctx.lang = "bar"
            self.assertEqual("bar", new_ctx.lang)

            self.assertEqual("foo", self.ctx.lang)

    def tearDown(self):
        del self.ctx


class Testcapture_events(unittest.TestCase):
    def test_capture_initiation(self):
        receiver_mock = unittest.mock.Mock()

        def receiver():
            receiver_mock.next()
            while True:
                receiver_mock.send((yield))

        dest = []

        capturer = iter(xso_model.capture_events(receiver(), dest))

        self.assertIsNone(next(capturer))
        receiver_mock.next.assert_called_with()
        self.assertSequenceEqual(
            [],
            dest
        )

    def test_capture_and_forward_events(self):
        receiver_mock = unittest.mock.Mock()

        def receiver():
            receiver_mock.next()
            while True:
                receiver_mock.send((yield))

        dest = []

        capturer = iter(xso_model.capture_events(receiver(), dest))

        more_args = [object(), object(), object()]
        next(capturer)
        for i, arg in enumerate(more_args):
            capturer.send(arg)
            receiver_mock.send.assert_called_with(arg)
            self.assertSequenceEqual(
                more_args[:i+1],
                dest
            )

    def test_clear_destination_on_exception(self):
        receiver_mock = unittest.mock.Mock()

        def receiver():
            receiver_mock.next()
            receiver_mock.send((yield))
            receiver_mock.send((yield))
            raise BaseException()

        dest = []

        capturer = iter(xso_model.capture_events(receiver(), dest))

        more_args = [object(), object()]
        next(capturer)
        for i, arg in enumerate(more_args[:1]):
            capturer.send(arg)
            receiver_mock.send.assert_called_with(arg)
            self.assertSequenceEqual(
                more_args[:i+1],
                dest
            )

        with self.assertRaises(BaseException):
            capturer.send(more_args[-1])

        self.assertSequenceEqual([], dest)

    def test_clear_destination_on_exception_during_startup(self):
        def receiver():
            raise BaseException()
            yield

        dest = []

        capturer = iter(xso_model.capture_events(receiver(), dest))

        with self.assertRaises(BaseException):
            next(capturer)

        self.assertSequenceEqual([], dest)

    def test_clear_destination_on_close_while_active(self):
        receiver_mock = unittest.mock.Mock()

        def receiver():
            receiver_mock.next()
            receiver_mock.send((yield))
            receiver_mock.send((yield))

        dest = []

        capturer = iter(xso_model.capture_events(receiver(), dest))

        next(capturer)
        capturer.close()

        self.assertSequenceEqual([], dest)

    def test_keep_destination_on_close_afterwards(self):
        receiver_mock = unittest.mock.Mock()

        def receiver():
            receiver_mock.next()
            receiver_mock.send((yield))

        dest = []
        ev_args = object()

        capturer = iter(xso_model.capture_events(receiver(), dest))

        next(capturer)
        with self.assertRaises(StopIteration):
            capturer.send(ev_args)
        capturer.close()

        self.assertSequenceEqual([ev_args], dest)

    def test_forward_result_from_receiver(self):
        result = object()
        receiver_mock = unittest.mock.Mock()

        def receiver():
            receiver_mock.next()
            receiver_mock.send((yield))
            return result

        dest = []
        ev_args = object()

        capturer = iter(xso_model.capture_events(receiver(), dest))

        next(capturer)
        with self.assertRaises(StopIteration) as ctx:
            capturer.send(ev_args)

        self.assertIs(ctx.exception.value, result)


class Testevents_to_sax(unittest.TestCase):
    def setUp(self):
        self.dest = unittest.mock.Mock()

    def test_start(self):
        xso_model.events_to_sax(
            [
                ("start", "uri:foo", "bar", {"a": "b"}),
            ],
            self.dest
        )
        self.dest.startElementNS.assert_called_with(
            ("uri:foo", "bar"),
            None,
            {"a": "b"}
        )

    def test_start_and_end(self):
        xso_model.events_to_sax(
            [
                ("start", "uri:foo", "bar", {"a": "b"}),
                ("end", ),
            ],
            self.dest
        )

        self.assertSequenceEqual(
            self.dest.mock_calls,
            [
                unittest.mock.call.startElementNS(
                    ("uri:foo", "bar"),
                    None,
                    {"a": "b"}
                ),
                unittest.mock.call.endElementNS(
                    ("uri:foo", "bar"),
                    None,
                ),
            ]
        )

    def test_text(self):
        xso_model.events_to_sax(
            [
                ("start", "uri:foo", "bar", {"a": "b"}),
                ("text", "foo"),
                ("end", ),
            ],
            self.dest
        )

        self.assertSequenceEqual(
            self.dest.mock_calls,
            [
                unittest.mock.call.startElementNS(
                    ("uri:foo", "bar"),
                    None,
                    {"a": "b"}
                ),
                unittest.mock.call.characters("foo"),
                unittest.mock.call.endElementNS(
                    ("uri:foo", "bar"),
                    None,
                ),
            ]
        )

    def test_nested_stuff(self):
        xso_model.events_to_sax(
            [
                ("start", "uri:foo", "bar", {"a": "b"}),
                ("start", "uri:foo", "baz", {}),
                ("end", ),
                ("start", "uri:foo", "baz", {}),
                ("end", ),
                ("end", ),
            ],
            self.dest
        )

        self.assertSequenceEqual(
            self.dest.mock_calls,
            [
                unittest.mock.call.startElementNS(
                    ("uri:foo", "bar"),
                    None,
                    {"a": "b"}
                ),
                unittest.mock.call.startElementNS(
                    ("uri:foo", "baz"),
                    None,
                    {}
                ),
                unittest.mock.call.endElementNS(
                    ("uri:foo", "baz"),
                    None,
                ),
                unittest.mock.call.startElementNS(
                    ("uri:foo", "baz"),
                    None,
                    {}
                ),
                unittest.mock.call.endElementNS(
                    ("uri:foo", "baz"),
                    None,
                ),
                unittest.mock.call.endElementNS(
                    ("uri:foo", "bar"),
                    None,
                ),
            ]
        )

    def tearDown(self):
        del self.dest


class Test_CollectorContentHandlerFilter(unittest.TestCase):
    def setUp(self):
        self.r = unittest.mock.Mock()
        self.f = xso_model._CollectorContentHandlerFilter(self.r)

    def test_setDocumentLocator(self):
        self.f.setDocumentLocator(unittest.mock.sentinel.locator)
        self.r.setDocumentLocator.assert_called_once_with(
            unittest.mock.sentinel.locator,
        )

    def test_startDocument(self):
        self.f.startDocument()
        self.r.assert_not_called()

    def test_endDocument(self):
        self.f.endDocument()
        self.r.assert_not_called()

    def test_startPrefixMapping(self):
        self.f.startPrefixMapping(
            unittest.mock.sentinel.prefix,
            unittest.mock.sentinel.uri,
        )
        self.r.startPrefixMapping.assert_not_called()

    def test_endPrefixMapping(self):
        self.f.endPrefixMapping(
            unittest.mock.sentinel.prefix,
        )
        self.r.endPrefixMapping.assert_not_called()

    def test_startElement(self):
        self.f.startElement(
            unittest.mock.sentinel.name,
            unittest.mock.sentinel.attrs,
        )
        self.r.startElement.assert_called_once_with(
            unittest.mock.sentinel.name,
            unittest.mock.sentinel.attrs,
        )

    def test_startElementNS(self):
        self.f.startElementNS(
            unittest.mock.sentinel.name,
            unittest.mock.sentinel.qname,
            unittest.mock.sentinel.attrs,
        )
        self.r.startElementNS.assert_called_once_with(
            unittest.mock.sentinel.name,
            unittest.mock.sentinel.qname,
            unittest.mock.sentinel.attrs,
        )

    def test_endElement(self):
        self.f.endElement(
            unittest.mock.sentinel.name,
        )
        self.r.endElement.assert_called_once_with(
            unittest.mock.sentinel.name,
        )

    def test_endElementNS(self):
        self.f.endElementNS(
            unittest.mock.sentinel.name,
            unittest.mock.sentinel.qname,
        )
        self.r.endElementNS.assert_called_once_with(
            unittest.mock.sentinel.name,
            unittest.mock.sentinel.qname,
        )

    def test_characters(self):
        self.f.characters(unittest.mock.sentinel.data)
        self.r.characters.assert_called_once_with(unittest.mock.sentinel.data)

    def test_ignorableWhitespace(self):
        self.f.ignorableWhitespace(unittest.mock.sentinel.data)
        self.r.ignorableWhitespace.assert_called_once_with(
            unittest.mock.sentinel.data
        )

    def test_processingInstruction(self):
        self.f.processingInstruction(
            unittest.mock.sentinel.target,
            unittest.mock.sentinel.data,
        )
        self.r.processingInstruction.assert_called_once_with(
            unittest.mock.sentinel.target,
            unittest.mock.sentinel.data,
        )

    def test_skippedEntity(self):
        self.f.skippedEntity(unittest.mock.sentinel.name)
        self.r.skippedEntity.assert_called_once_with(
            unittest.mock.sentinel.name
        )


class TestXSOEnumMixin(unittest.TestCase):
    def test_is_not_an_enum(self):
        self.assertFalse(issubclass(xso_model.XSOEnumMixin,
                                    enum.Enum))

    def setUp(self):
        tag = namespaces.stanzas, "bad-request"

        class FakeEnum:
            def __init__(self):
                super().__init__()
                self.name = "BAD_REQUEST"
                self.value = tag

        class Mixed(xso_model.XSOEnumMixin, FakeEnum):
            pass

        self.Mixed = Mixed
        self.m = self.Mixed(*tag)

    def test_create_name(self):
        self.assertEqual(
            self.m._create_name(),
            "BadRequest",
        )

    def test_create_class(self):
        with contextlib.ExitStack() as stack:
            XMLStreamClass = stack.enter_context(unittest.mock.patch(
                "aioxmpp.xso.model.XMLStreamClass"
            ))

            _create_name = stack.enter_context(unittest.mock.patch.object(
                self.m, "_create_name",
            ))
            _create_name.return_value = unittest.mock.sentinel.name

            stack.enter_context(unittest.mock.patch.object(
                self.m,
                "value",
                new=unittest.mock.sentinel.value,
            ))

            c = self.m._create_class()

        _create_name.assert_called_once_with()

        XMLStreamClass.assert_called_once_with(
            unittest.mock.sentinel.name,
            (xso_model.XSO,),
            unittest.mock.ANY,
        )

        _, (_, _, namespace), _ = XMLStreamClass.mock_calls[-1]

        self.assertEqual(
            namespace["__qualname__"],
            "{}.BAD_REQUEST.xso_class".format(
                type(self.m).__qualname__,
            )
        )

        self.assertEqual(
            namespace["TAG"],
            unittest.mock.sentinel.value,
        )

        self.assertIs(
            namespace["enum_member"],
            self.m,
        )

    def test_creates_and_assigns_class(self):
        with unittest.mock.patch.object(
                xso_model.XSOEnumMixin,
                "_create_class") as _create_class:
            _create_class.return_value = unittest.mock.sentinel.xso_class

            m = self.Mixed(namespaces.stanzas, "bad-request")

        _create_class.assert_called_once_with()

        self.assertEqual(
            m.xso_class,
            unittest.mock.sentinel.xso_class,
        )

    def test_to_xso_creates_instance(self):
        with unittest.mock.patch.object(self.m, "xso_class") as class_:
            class_.return_value = unittest.mock.sentinel.instance

            result = self.m.to_xso()

        class_.assert_called_once_with()

        self.assertEqual(
            result,
            unittest.mock.sentinel.instance,
        )

    def test_to_xso_creates_new_instance_each_time(self):
        with unittest.mock.patch.object(self.m, "xso_class") as class_:
            class_.return_value = unittest.mock.sentinel.instance1

            result = self.m.to_xso()

            class_.assert_called_once_with()
            class_.reset_mock()

            class_.return_value = unittest.mock.sentinel.instance2

            result = self.m.to_xso()

        class_.assert_called_once_with()

        self.assertEqual(
            result,
            unittest.mock.sentinel.instance2,
        )

    def test_enum_member_refers_to_itself(self):
        self.assertIs(self.m, self.m.enum_member)

    def test_xso_to_xso_returns_object(self):
        x = self.m.to_xso()
        self.assertIs(x, x.to_xso())

    def test_mixes_well_with_enum(self):
        class Mixed(xso_model.XSOEnumMixin, enum.Enum):
            BAD_REQUEST = (namespaces.stanzas, "bad-request")
            UNDEFINED_CONDITION = (namespaces.stanzas, "undefined-condition")

        self.assertTrue(issubclass(Mixed.BAD_REQUEST.xso_class,
                                   xso_model.XSO))

        self.assertEqual(
            Mixed.BAD_REQUEST.xso_class.__name__,
            "BadRequest",
        )

        self.assertEqual(
            Mixed.BAD_REQUEST.xso_class.__qualname__,
            "{}.BAD_REQUEST.xso_class".format(Mixed.__qualname__),
        )

        self.assertIs(
            Mixed.BAD_REQUEST.xso_class().enum_member,
            Mixed.BAD_REQUEST,
        )

        instance = Mixed.BAD_REQUEST.xso_class()

        self.assertIs(
            instance,
            instance.to_xso()
        )

        self.assertTrue(issubclass(Mixed.UNDEFINED_CONDITION.xso_class,
                                   xso_model.XSO))

        self.assertEqual(
            Mixed.UNDEFINED_CONDITION.xso_class.__name__,
            "UndefinedCondition",
        )

        self.assertEqual(
            Mixed.UNDEFINED_CONDITION.xso_class.__qualname__,
            "{}.UNDEFINED_CONDITION.xso_class".format(Mixed.__qualname__),
        )

        self.assertIs(
            Mixed.UNDEFINED_CONDITION.xso_class().enum_member,
            Mixed.UNDEFINED_CONDITION,
        )

        instance = Mixed.UNDEFINED_CONDITION.xso_class()

        self.assertIs(
            instance,
            instance.to_xso()
        )

    def test_mixes_well_with_the_compatibility_mixin(self):
        class Mixed(xso_model.XSOEnumMixin, structs.CompatibilityMixin,
                    enum.Enum):
            BAD_REQUEST = (namespaces.stanzas, "bad-request")

        self.assertEqual(
            Mixed.BAD_REQUEST,
            Mixed.BAD_REQUEST.value,
        )


class TestAbstractTextChild(unittest.TestCase):
    def test_is_xso(self):
        self.assertTrue(issubclass(
            xso.AbstractTextChild,
            xso.XSO
        ))

    def test_has_no_tag(self):
        self.assertFalse(hasattr(xso.AbstractTextChild, "TAG"))

    def test_lang_attr(self):
        self.assertIsInstance(
            xso.AbstractTextChild.lang.xq_descriptor,
            xso.LangAttr
        )

    def test_text_attr(self):
        self.assertIsInstance(
            xso.AbstractTextChild.text.xq_descriptor,
            xso.Text
        )
        self.assertIsNone(
            xso.AbstractTextChild.text.default
        )

    def test_init_default(self):
        atc = xso.AbstractTextChild()
        self.assertIsNone(atc.lang)
        self.assertFalse(atc.text)

    def test_init_args(self):
        atc = xso.AbstractTextChild(
            "foo",
            lang=structs.LanguageTag.fromstr("de-DE"))
        self.assertEqual(atc.text, "foo")
        self.assertEqual(atc.lang, structs.LanguageTag.fromstr("de-DE"))

    def test_equality(self):
        atc1 = xso.AbstractTextChild()
        atc2 = xso.AbstractTextChild()

        self.assertTrue(atc1 == atc2)
        self.assertFalse(atc1 != atc2)

        atc1.text = "foo"

        self.assertFalse(atc1 == atc2)
        self.assertTrue(atc1 != atc2)

        atc2.text = "foo"
        atc2.lang = structs.LanguageTag.fromstr("de-DE")

        self.assertFalse(atc1 == atc2)
        self.assertTrue(atc1 != atc2)

        atc1.lang = atc2.lang

        self.assertTrue(atc1 == atc2)
        self.assertFalse(atc1 != atc2)

    def test_equality_handles_incorrect_peer_type_gracefully(self):
        atc = xso.AbstractTextChild()
        self.assertFalse(atc is None)
        self.assertFalse(atc == "foo")
