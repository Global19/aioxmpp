import asyncio
import functools
import unittest
import unittest.mock
import weakref

from aioxmpp.callbacks import (
    TagDispatcher,
    TagListener,
    AsyncTagListener,
    OneshotTagListener,
    OneshotAsyncTagListener,
    Signal,
    AdHocSignal,
)

from .testutils import run_coroutine


class TestTagListener(unittest.TestCase):
    def test_data(self):
        ondata = unittest.mock.Mock()

        obj = object()

        listener = TagListener(ondata=ondata)
        listener.data(obj)
        ondata.assert_called_once_with(obj)

    def test_uninitialized_error(self):
        ondata = unittest.mock.Mock()

        listener = TagListener(ondata=ondata)
        listener.error(ValueError())

    def test_error(self):
        ondata = unittest.mock.Mock()
        onerror = unittest.mock.Mock()

        exc = ValueError()

        listener = TagListener(ondata, onerror)
        listener.error(exc)

        ondata.assert_not_called()
        onerror.assert_called_once_with(exc)


class TestTagDispatcher(unittest.TestCase):
    def test_add_callback(self):
        mock = unittest.mock.Mock()

        nh = TagDispatcher()
        nh.add_callback("tag", mock)
        with self.assertRaisesRegexp(ValueError,
                                     "only one listener is allowed"):
            nh.add_callback("tag", mock)

    def test_add_listener(self):
        mock = unittest.mock.Mock()

        l = TagListener(mock)

        nh = TagDispatcher()
        nh.add_listener("tag", l)
        with self.assertRaisesRegexp(ValueError,
                                     "only one listener is allowed"):
            nh.add_listener("tag", l)

    @unittest.mock.patch("aioxmpp.callbacks.AsyncTagListener")
    def test_add_callback_async(self, AsyncTagListener):
        data = unittest.mock.Mock()
        loop = unittest.mock.Mock()
        obj = object()

        nh = TagDispatcher()
        nh.add_callback_async("tag", data, loop=loop)

        self.assertSequenceEqual(
            [
                unittest.mock.call(data, loop=loop)
            ],
            AsyncTagListener.mock_calls
        )
        del AsyncTagListener.mock_calls[:]

        nh.unicast("tag", obj)

        self.assertSequenceEqual(
            [
                unittest.mock.call().data(obj),
                unittest.mock.call().data().__bool__(),
            ],
            AsyncTagListener.mock_calls
        )

    def test_add_future(self):
        mock = unittest.mock.Mock()
        obj = object()

        nh = TagDispatcher()
        nh.add_future("tag", mock)
        nh.unicast("tag", obj)
        with self.assertRaises(KeyError):
            # futures must be oneshots
            nh.unicast("tag", obj)

        nh.add_future("tag", mock)
        nh.broadcast_error(obj)
        with self.assertRaises(KeyError):
            # futures must be oneshots
            nh.unicast("tag", obj)

        self.assertSequenceEqual(
            [
                unittest.mock.call.set_result(obj),
                unittest.mock.call.set_exception(obj),
            ],
            mock.mock_calls
        )

    @unittest.mock.patch("aioxmpp.callbacks.OneshotAsyncTagListener")
    def test_add_future_async(self, OneshotAsyncTagListener):
        mock = unittest.mock.Mock()
        loop = unittest.mock.Mock()
        obj = object()

        nh = TagDispatcher()
        nh.add_future_async("tag", mock, loop=loop)

        self.assertSequenceEqual(
            [
                unittest.mock.call(mock.set_result,
                                   mock.set_exception,
                                   loop=loop)
            ],
            OneshotAsyncTagListener.mock_calls
        )
        del OneshotAsyncTagListener.mock_calls[:]

        nh.unicast("tag", obj)

        self.assertSequenceEqual(
            [
                unittest.mock.call().data(obj),
                unittest.mock.call().data().__bool__(),
            ],
            OneshotAsyncTagListener.mock_calls
        )

    def test_unicast(self):
        mock = unittest.mock.Mock()
        mock.return_value = False
        obj = object()

        nh = TagDispatcher()
        nh.add_callback("tag", mock)
        nh.unicast("tag", obj)
        nh.unicast("tag", obj)

        self.assertSequenceEqual(
            [
                unittest.mock.call(obj),
                unittest.mock.call(obj),
            ],
            mock.mock_calls
        )

    def test_unicast_fails_for_nonexistent(self):
        obj = object()
        nh = TagDispatcher()
        with self.assertRaises(KeyError):
            nh.unicast("tag", obj)

    def test_unicast_to_oneshot(self):
        mock = unittest.mock.Mock()
        obj = object()

        l = OneshotTagListener(mock)

        nh = TagDispatcher()
        nh.add_listener("tag", l)

        nh.unicast("tag", obj)
        with self.assertRaises(KeyError):
            nh.unicast("tag", obj)

        self.assertSequenceEqual(
            [
                unittest.mock.call(obj)
            ],
            mock.mock_calls
        )

    def test_unicast_removes_for_true_result(self):
        mock = unittest.mock.Mock()
        mock.return_value = True
        obj = object()

        nh = TagDispatcher()
        nh.add_callback("tag", mock)
        nh.unicast("tag", obj)
        with self.assertRaises(KeyError):
            nh.unicast("tag", obj)

        mock.assert_called_once_with(obj)

    def test_broadcast_error_to_oneshot(self):
        data = unittest.mock.Mock()
        error = unittest.mock.Mock()
        obj = object()

        l = OneshotTagListener(data, error)

        nh = TagDispatcher()
        nh.add_listener("tag", l)

        nh.broadcast_error(obj)
        with self.assertRaises(KeyError):
            nh.unicast("tag", obj)

        self.assertSequenceEqual(
            [
                unittest.mock.call(obj)
            ],
            error.mock_calls
        )
        self.assertFalse(data.mock_calls)

    def test_remove_listener(self):
        mock = unittest.mock.Mock()
        nh = TagDispatcher()
        nh.add_callback("tag", mock)
        nh.remove_listener("tag")
        with self.assertRaises(KeyError):
            nh.unicast("tag", object())
        mock.assert_not_called()

    def test_broadcast_error(self):
        data = unittest.mock.Mock()
        error1 = unittest.mock.Mock()
        error1.return_value = False
        error2 = unittest.mock.Mock()
        error2.return_value = False

        l1 = TagListener(data, error1)
        l2 = TagListener(data, error2)

        obj = object()

        nh = TagDispatcher()
        nh.add_listener("tag1", l1)
        nh.add_listener("tag2", l2)

        nh.broadcast_error(obj)
        nh.broadcast_error(obj)

        data.assert_not_called()
        self.assertSequenceEqual(
            [
                unittest.mock.call(obj),
                unittest.mock.call(obj),
            ],
            error1.mock_calls
        )
        self.assertSequenceEqual(
            [
                unittest.mock.call(obj),
                unittest.mock.call(obj),
            ],
            error2.mock_calls
        )

    def test_broadcast_error_removes_on_true_result(self):
        data = unittest.mock.Mock()
        error1 = unittest.mock.Mock()
        error1.return_value = True

        l1 = TagListener(data, error1)

        obj = object()

        nh = TagDispatcher()
        nh.add_listener("tag1", l1)

        nh.broadcast_error(obj)
        nh.broadcast_error(obj)

        data.assert_not_called()
        self.assertSequenceEqual(
            [
                unittest.mock.call(obj),
            ],
            error1.mock_calls
        )

    def test_close(self):
        data = unittest.mock.Mock()
        error1 = unittest.mock.Mock()
        error2 = unittest.mock.Mock()

        l1 = TagListener(data, error1)
        l2 = TagListener(data, error2)

        obj = object()

        nh = TagDispatcher()
        nh.add_listener("tag1", l1)
        nh.add_listener("tag2", l2)

        nh.close_all(obj)

        data.assert_not_called()
        error1.assert_called_once_with(obj)
        error2.assert_called_once_with(obj)

        with self.assertRaises(KeyError):
            nh.remove_listener("tag1")
        with self.assertRaises(KeyError):
            nh.remove_listener("tag2")
        with self.assertRaises(KeyError):
            nh.unicast("tag1", None)
        with self.assertRaises(KeyError):
            nh.unicast("tag2", None)


class TestAsyncTagListener(unittest.TestCase):
    def test_everything(self):
        data = unittest.mock.MagicMock()
        error = unittest.mock.MagicMock()
        loop = unittest.mock.MagicMock()
        obj = object()
        tl = AsyncTagListener(data, error, loop=loop)
        self.assertFalse(tl.data(obj))
        self.assertFalse(tl.error(obj))

        self.assertFalse(data.mock_calls)
        self.assertFalse(error.mock_calls)
        self.assertSequenceEqual(
            [
                unittest.mock.call.__bool__(),
                unittest.mock.call.call_soon(data, obj),
                unittest.mock.call.call_soon(error, obj),
            ],
            loop.mock_calls
        )


class TestOneshotAsyncTagListener(unittest.TestCase):
    def test_everything(self):
        data = unittest.mock.MagicMock()
        error = unittest.mock.MagicMock()
        loop = unittest.mock.MagicMock()
        obj = object()
        tl = OneshotAsyncTagListener(data, error, loop=loop)
        self.assertTrue(tl.data(obj))
        self.assertTrue(tl.error(obj))

        self.assertFalse(data.mock_calls)
        self.assertFalse(error.mock_calls)
        self.assertSequenceEqual(
            [
                unittest.mock.call.__bool__(),
                unittest.mock.call.call_soon(data, obj),
                unittest.mock.call.call_soon(error, obj),
            ],
            loop.mock_calls
        )


class TestAdHocSignal(unittest.TestCase):
    def test_connect_and_fire(self):
        signal = AdHocSignal()

        fun = unittest.mock.MagicMock()
        fun.return_value = None

        signal.connect(fun)

        signal.fire()
        signal.fire()

        self.assertSequenceEqual(
            [
                unittest.mock.call(),
                unittest.mock.call(),
            ],
            fun.mock_calls
        )

    def test_connect_and_call(self):
        signal = AdHocSignal()

        fun = unittest.mock.MagicMock()
        fun.return_value = None

        signal.connect(fun)

        signal()

        fun.assert_called_once_with()

    def test_connect_weak_uses_weakref(self):
        signal = AdHocSignal()

        with unittest.mock.patch("weakref.ref") as ref:
            fun = unittest.mock.MagicMock()
            signal.connect(fun, AdHocSignal.WEAK)
            ref.assert_called_once_with(fun)

    def test_connect_does_not_use_weakref(self):
        signal = AdHocSignal()

        with unittest.mock.patch("weakref.ref") as ref:
            fun = unittest.mock.MagicMock()
            signal.connect(fun)
            self.assertFalse(ref.mock_calls)

    @unittest.mock.patch("weakref.ref")
    def test_fire_removes_stale_references(self, ref):
        signal = AdHocSignal()

        fun = unittest.mock.MagicMock()
        fun.return_value = None
        ref().return_value = None

        signal.connect(fun, AdHocSignal.WEAK)

        signal.fire()

        self.assertFalse(signal._connections)

    def test_connect_async(self):
        signal = AdHocSignal()

        mock = unittest.mock.MagicMock()
        fun = functools.partial(mock)

        signal.connect(fun, AdHocSignal.ASYNC)
        signal.fire()

        mock.assert_not_called()

        run_coroutine(asyncio.sleep(0))

        mock.assert_called_once_with()

    def test_fire_with_arguments(self):
        signal = AdHocSignal()

        fun = unittest.mock.MagicMock()

        signal.connect(fun)

        signal("a", 1, foo=None)

        fun.assert_called_once_with("a", 1, foo=None)

    def test_remove_callback_on_true_result(self):
        signal = AdHocSignal()

        fun = unittest.mock.MagicMock()
        fun.return_value = True

        signal.connect(fun)

        signal()

        self.assertSequenceEqual(
            [
                unittest.mock.call(),
            ],
            fun.mock_calls
        )

        signal()

        self.assertSequenceEqual(
            [
                unittest.mock.call(),
            ],
            fun.mock_calls
        )

    def test_remove_by_token(self):
        signal = AdHocSignal()

        fun = unittest.mock.MagicMock()
        fun.return_value = None

        token = signal.connect(fun)

        signal()

        self.assertSequenceEqual(
            [
                unittest.mock.call(),
            ],
            fun.mock_calls
        )

        signal()

        self.assertSequenceEqual(
            [
                unittest.mock.call(),
                unittest.mock.call(),
            ],
            fun.mock_calls
        )

        signal.disconnect(token)

        signal()

        self.assertSequenceEqual(
            [
                unittest.mock.call(),
                unittest.mock.call(),
            ],
            fun.mock_calls
        )

    def test_disconnect_is_idempotent(self):
        signal = AdHocSignal()

        fun = unittest.mock.MagicMock()
        fun.return_value = None

        token = signal.connect(fun)

        signal.disconnect(token)
        signal.disconnect(token)

    def test_context_connect(self):
        signal = AdHocSignal()

        fun = unittest.mock.MagicMock()
        fun.return_value = None

        with signal.context_connect(fun):
            signal("foo")
        signal("bar")
        with signal.context_connect(fun) as token:
            signal("baz")
            signal.disconnect(token)
            signal("fnord")

        self.assertSequenceEqual(
            [
                unittest.mock.call("foo"),
                unittest.mock.call("baz"),
            ],
            fun.mock_calls
        )

    def test_context_connect_forwards_exceptions_and_disconnects(self):
        signal = AdHocSignal()

        fun = unittest.mock.MagicMock()
        fun.return_value = None

        exc = ValueError()
        with self.assertRaises(ValueError) as ctx:
            with signal.context_connect(fun):
                signal("foo")
                raise exc
        signal("bar")

        self.assertIs(exc, ctx.exception)

        self.assertSequenceEqual(
            [
                unittest.mock.call("foo"),
            ],
            fun.mock_calls
        )


class TestSignal(unittest.TestCase):
    def test_get(self):
        class Foo:
            s = Signal()

        instance1 = Foo()
        instance2 = Foo()

        self.assertIsNot(instance1.s, instance2.s)
        self.assertIs(instance1.s, instance1.s)
        self.assertIs(instance2.s, instance2.s)

        self.assertIsInstance(instance1.s, AdHocSignal)
        self.assertIsInstance(instance2.s, AdHocSignal)

    def test_reject_set(self):
        class Foo:
            s = Signal()

        instance = Foo()

        with self.assertRaises(AttributeError):
            instance.s = "foo"

    def test_reject_delete(self):
        class Foo:
            s = Signal()

        instance = Foo()

        with self.assertRaises(AttributeError):
            del instance.s
