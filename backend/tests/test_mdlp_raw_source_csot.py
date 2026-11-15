"""Actual pinned PyMongo timeout mutation, without Mongo clients or sockets.

This is a dependency contract test, not a real Mongo wire/latency proof.
Only the connection's transport is a recording shell. apply_timeout and
set_conn_timeout are the unmodified installed PyMongo 4.9.2 implementations.
"""
import asyncio
import hashlib
import inspect
import time
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

import pymongo
from pymongo import _csot, timeout
from pymongo.errors import ExecutionTimeout
from pymongo.errors import NetworkTimeout
from pymongo.pool_options import PoolOptions
from pymongo.synchronous.database import Database
from pymongo.synchronous.pool import Connection, ORDERED_TYPES
from pymongo.synchronous import network
import pytest

from api import mdlp_raw_source as source


GTIN = '04601969010459'
APPLY_TIMEOUT_SHA256 = '6ae1fffcf5f76682326b2c63f1754a7911a2f9cef3a81cfb0599d22bf06e28fb'
DATABASE_COMMAND_SHA256 = 'a51aeb014ac525f04ae3f5f448d98f4cf876dc79bc41ed4da8a16abf6f353319'
NETWORK_COMMAND_SHA256 = '0108c728834ab644b7a0ef99d7c22ec3d410530502f5a19fc543eae91e0a35c7'


class RecordingTransport:
    def __init__(self):
        self.timeouts = []

    def settimeout(self, seconds):
        self.timeouts.append(seconds)

    def close(self):
        pass


def connection_shell():
    # Bypass all Connection construction: no MongoClient, socket or network.
    conn = Connection.__new__(Connection)
    conn.conn = RecordingTransport()
    conn.opts = PoolOptions()
    conn.last_timeout = None
    conn.more_to_come = False
    conn.connect_rtt = 0.0
    conn.max_wire_version = 25
    conn.address = ('unconnected.invalid', 0)
    conn.listeners = None
    conn.op_msg_enabled = True
    conn.is_mongos = False
    conn.is_writable = True
    conn.max_bson_size = None
    conn.compression_context = None
    conn.ready = False
    conn.closed = False
    conn.enabled_for_cmap = False
    conn.enabled_for_logging = False
    conn.cancel_context = SimpleNamespace(cancel=lambda: None)
    return conn


class ActualTimeoutCommandShell:
    def __init__(self, *, remaining=None, rtt=0.0):
        self.conn = connection_shell()
        self.before = []
        self.after = []
        self.remaining = remaining
        self.rtt = rtt

    def command(self, command):
        self.before.append(dict(command))
        if self.remaining is not None:
            # Deterministic elapsed-time boundary. Driver functions are intact.
            _csot.DEADLINE.set(time.monotonic() + self.remaining)
        _csot.set_rtt(self.rtt)
        self.conn.apply_timeout(None, command)
        self.after.append(dict(command))
        return {'cursor': {'id': 0, 'firstBatch': []}}


def test_dependency_matches_actual_reviewed_pymongo492_function():
    assert pymongo.version == '4.9.2'
    assert hashlib.sha256(inspect.getsource(Connection.apply_timeout).encode()).hexdigest() == APPLY_TIMEOUT_SHA256
    assert hashlib.sha256(inspect.getsource(Database._command).encode()).hexdigest() == DATABASE_COMMAND_SHA256
    assert hashlib.sha256(inspect.getsource(network.command).encode()).hexdigest() == NETWORK_COMMAND_SHA256
    assert isinstance(source._RawAggregateCommand(), ORDERED_TYPES)
    assert issubclass(source._RawAggregateCommand, dict)
    assert not isinstance({}, ORDERED_TYPES)


def test_read_raw_actual_driver_rewrite_never_raises_explicit300_bound():
    assert source.MONGO_MS == 300
    assert source.DRIVER_SECONDS == .3
    assert source.RESOLVER_SECONDS == .5
    database = ActualTimeoutCommandShell()
    assert source.read_raw(database, [GTIN]) == []
    assert len(database.before) == len(database.after) == 1
    assert database.before[0]['maxTimeMS'] == 300
    assert 0 < database.after[0]['maxTimeMS'] <= 300
    assert 0 < database.conn.conn.timeouts[0] <= .3


def test_regression_old450_budget_really_overwrites_explicit300(monkeypatch):
    monkeypatch.setattr(source, 'DRIVER_SECONDS', .45)
    database = ActualTimeoutCommandShell()
    with pytest.raises(TimeoutError):
        source.read_raw(database, [GTIN])
    assert database.before[0]['maxTimeMS'] == 300
    assert database.after == []
    assert database.conn.conn.timeouts == []
    # A test of the pre-driver dict alone would have missed this mutation.


def test_actual_delayed_context_uses_smaller_remaining_budget():
    database = ActualTimeoutCommandShell(remaining=.1, rtt=.01)
    assert source.read_raw(database, [GTIN]) == []
    assert 0 < database.after[0]['maxTimeMS'] <= 90
    assert 0 < database.conn.conn.timeouts[0] <= .1


def test_actual_expired_or_rtt_exceeded_context_fails_before_transport():
    for remaining, rtt in [(-.01, 0.0), (.01, .02)]:
        database = ActualTimeoutCommandShell(remaining=remaining, rtt=rtt)
        with pytest.raises(ExecutionTimeout):
            source.read_raw(database, [GTIN])
        assert len(database.before) == 1
        assert database.after == []
        assert database.conn.conn.timeouts == []


def test_submillisecond_driver_floor_is_recorded_not_claimed_positive():
    conn = connection_shell()
    command = {'maxTimeMS': 300}
    # Pin only the monotonic observation, not the dependency implementation.
    # A fixed clock avoids flakiness caused by the test scheduler crossing 1ms.
    with patch('pymongo._csot.time.monotonic', return_value=100.0):
        with timeout(.0005):
            conn.apply_timeout(None, command)
    assert command['maxTimeMS'] == 0
    assert 0 < conn.conn.timeouts[0] < .001
    assert not 0 < command['maxTimeMS'] <= 300


@pytest.mark.parametrize('value', [0, -1, 301, 449, True, False, .3, 300.0, None, '300'])
def test_guard_rejects_nonpositive_above300_and_nonexact_int_before_assignment(value):
    command = source._RawAggregateCommand({'aggregate': 'medications_raw', 'maxTimeMS': 300})
    with pytest.raises(TimeoutError):
        command['maxTimeMS'] = value
    assert command['maxTimeMS'] == 300
    command['not_a_timeout'] = value
    assert command['not_a_timeout'] is value


def test_guard_accepts_only_positive_int_rewrites_and_preserves_other_keys():
    command = source._RawAggregateCommand({'maxTimeMS': 300})
    for value in [1, 90, 299, 300]:
        command['maxTimeMS'] = value
        assert command['maxTimeMS'] == value
    command['cursor'] = {'batchSize': 2}
    assert command['cursor'] == {'batchSize': 2}


class EncoderBoundary(Exception):
    """An observation boundary: no BSON encoding, send or receive occurs."""


class FullDriverCommandShell(ActualTimeoutCommandShell):
    def __init__(self, *, remaining=None, rtt=0.0):
        super().__init__(remaining=remaining, rtt=rtt)
        self.mapping = None
        self.cluster_time_mappings = []
        client_shell = SimpleNamespace(
            _tmp_session=lambda session: nullcontext(None),
            _send_cluster_time=lambda command, session: self.cluster_time_mappings.append(command),
            _encrypter=None,
        )
        # No Database/MongoClient initialization, server selection or sockets.
        self.db_shell = SimpleNamespace(_client=client_shell, _name='offline')

    def command(self, command):
        self.before.append(dict(command))
        self.mapping = command
        if self.remaining is not None:
            _csot.DEADLINE.set(time.monotonic() + self.remaining)
        _csot.set_rtt(self.rtt)
        # These are the installed dependency functions, not copies of their
        # implementation. Connection.command includes its real decorators.
        return Database._command(self.db_shell, self.conn, command)


@pytest.mark.parametrize('remaining', [None, .1])
def test_actual_full_driver_chain_preserves_guard_mapping_before_encoder(remaining):
    database = FullDriverCommandShell(remaining=remaining)
    encoded_mappings = []
    def encoder(flags, command, *args, **kwargs):
        encoded_mappings.append(command)
        assert command is database.mapping
        assert type(command) is source._RawAggregateCommand
        assert type(command['maxTimeMS']) is int and 1 <= command['maxTimeMS'] <= 300
        raise EncoderBoundary('no actual encoding or send')
    with patch('pymongo.synchronous.network.message._op_msg', side_effect=encoder) as encoding:
        with patch('pymongo.synchronous.network.sendall') as send:
            with pytest.raises(EncoderBoundary):
                source.read_raw(database, [GTIN])
    assert database.before[0]['maxTimeMS'] == 300
    assert len(encoded_mappings) == 1 and encoding.call_count == 1
    assert database.cluster_time_mappings[0] is database.mapping
    assert 0 < database.conn.conn.timeouts[0] <= .3
    send.assert_not_called()


@pytest.mark.parametrize('driver_seconds,remaining', [(.45, None), (.3, .0005)])
def test_actual_full_driver_chain_unsafe_rewrite_fails_before_encoding_and_send(monkeypatch, driver_seconds, remaining):
    monkeypatch.setattr(source, 'DRIVER_SECONDS', driver_seconds)
    database = FullDriverCommandShell(remaining=remaining)
    with patch('pymongo._csot.time.monotonic', return_value=100.0):
        with patch('pymongo.synchronous.network.message._op_msg') as encoding:
            with patch('pymongo.synchronous.network.sendall') as send:
                # Actual Connection.command converts local TimeoutError to
                # NetworkTimeout after closing the unconnected transport.
                with pytest.raises(NetworkTimeout, match='raw aggregate server deadline outside bound'):
                    source.read_raw(database, [GTIN])
    assert database.mapping['maxTimeMS'] == 300
    assert database.conn.conn.timeouts == []
    assert database.conn.closed
    assert database.cluster_time_mappings[0] is database.mapping
    encoding.assert_not_called()
    send.assert_not_called()


def test_actual_full_driver_expiry_fails_before_encoding_or_send():
    database = FullDriverCommandShell(remaining=.01, rtt=.02)
    with patch('pymongo.synchronous.network.message._op_msg') as encoding:
        with patch('pymongo.synchronous.network.sendall') as send:
            with pytest.raises(ExecutionTimeout):
                source.read_raw(database, [GTIN])
    assert database.mapping['maxTimeMS'] == 300
    assert database.conn.conn.timeouts == []
    encoding.assert_not_called()
    send.assert_not_called()


def test_expired_actual_driver_error_yields_no_rows_and_worker_slots_settle():
    async def run():
        database = ActualTimeoutCommandShell(remaining=-.01)
        resolver = source.AsyncRawSource(SimpleNamespace(delegate=database))
        try:
            with pytest.raises(ExecutionTimeout):
                await resolver.get([GTIN])
            for _ in range(100):
                if resolver.slots._value == 2:
                    break
                await asyncio.sleep(.001)
            assert resolver.slots._value == 2
            assert database.after == []
            assert database.conn.conn.timeouts == []
            assert source._PROCESS_SLOTS.acquire(blocking=False)
            try:
                assert source._PROCESS_SLOTS.acquire(blocking=False)
                source._PROCESS_SLOTS.release()
            finally:
                source._PROCESS_SLOTS.release()
        finally:
            if resolver.pool:
                resolver.pool.shutdown(wait=True)
    asyncio.run(run())


@pytest.mark.parametrize('remaining', [.0005, .45])
def test_local_guard_error_yields_no_rows_and_worker_slots_settle(remaining):
    async def run():
        database = ActualTimeoutCommandShell(remaining=remaining)
        resolver = source.AsyncRawSource(SimpleNamespace(delegate=database))
        try:
            with pytest.raises(TimeoutError):
                await resolver.get([GTIN])
            for _ in range(100):
                if resolver.slots._value == 2:
                    break
                await asyncio.sleep(.001)
            assert resolver.slots._value == 2
            assert database.after == []
            assert database.conn.conn.timeouts == []
        finally:
            if resolver.pool:
                resolver.pool.shutdown(wait=True)
    # Pin the observed boundary within each worker via remaining ContextVar;
    # the actual dependency's apply_timeout function remains unmodified.
    asyncio.run(run())
