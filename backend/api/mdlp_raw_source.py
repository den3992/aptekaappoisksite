"""Bounded current raw projections; no credentials, source XLSX or medical text.

The semaphore follows concurrent.futures worker completion, not cancellation of
an asyncio wrapper. Normal fixed aggregate is a single non-retried DB command.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import threading
from .mdlp_variant_form_evidence import FIELDS,MAX_FIELD_BYTES,MAX_ROW_BYTES

MAX_PAIRS = 32
MAX_RESULT_BYTES = 256 * 1024
MONGO_MS = 300
DRIVER_SECONDS = .45
RESOLVER_SECONDS = .5
_PROCESS_SLOTS = threading.BoundedSemaphore(2)


def pipeline(gtins):
    if (not isinstance(gtins,list) or not 1<=len(gtins)<=MAX_PAIRS
            or any(not isinstance(g,str) or len(g)!=14 or not g.isascii() or not g.isdigit() for g in gtins)
            or len(set(gtins))!=len(gtins)):
        raise ValueError('bounded exact GTIN14 query required')
    lengths = [{'$cond':[{'$eq':[{'$type':'$'+key},'string']},
                         {'$strLenBytes':'$'+key},MAX_ROW_BYTES+1]} for key in FIELDS]
    valid = {'$and':[{'$and':[{'$gt':[length,0]},{'$lte':[length,MAX_FIELD_BYTES]}]}
                      for length in lengths] + [{'$lte':[{'$add':lengths},MAX_ROW_BYTES]}]}
    return [{'$match':{'gtin':{'$in':gtins}}},{'$limit':len(gtins)+1},
            {'$project':{'_id':0,'gtin':{'$cond':[{'$eq':[{'$type':'$gtin'},'string']},'$gtin',None]},
                         'raw':{'$cond':[valid,{key:'$'+key for key in FIELDS},None]}}}]


def read_raw(database, gtins):
    from pymongo import timeout
    stages = pipeline(gtins)
    # PyMongo Database.command does not use the retryable-read API. CSOT bounds
    # driver/server selection and network work, not just the awaiter's lifetime.
    with timeout(DRIVER_SECONDS):
        reply = database.command({'aggregate':'medications_raw','pipeline':stages,
                                  'cursor':{'batchSize':len(gtins)+1},'maxTimeMS':MONGO_MS,
                                  'hint':{'gtin':1},'allowDiskUse':False})
        cursor = reply.get('cursor',{})
        if cursor.get('id') != 0:
            if type(cursor.get('id')) is int and cursor['id']:
                database.command({'killCursors':'medications_raw','cursors':[cursor['id']]})
            raise ValueError('raw projection did not finish in one bounded batch')
        batch = cursor.get('firstBatch')
        # N+1 is an overflow sentinel, not a complete result: $limit can hide
        # a later conflicting duplicate even when the cursor is already closed.
        if not isinstance(batch,list) or len(batch)>len(gtins):
            raise ValueError('raw projection result exceeds count bound')
        if len(json.dumps(batch,ensure_ascii=False,separators=(',',':')).encode())>MAX_RESULT_BYTES:
            raise ValueError('raw projection exceeds byte bound')
        rows=[]
        for row in batch:
            if not isinstance(row,dict) or set(row)!={'gtin','raw'} or row['gtin'] not in gtins:
                raise ValueError('foreign or malformed guarded raw projection')
            raw = row['raw']
            if raw is None:
                rows.append({'gtin':row['gtin'],'invalid':True})
            elif isinstance(raw,dict) and raw.get('gtin')==row['gtin']:
                rows.append(raw)
            else:
                raise ValueError('guarded raw GTIN differs')
        return rows


class AsyncRawSource:
    def __init__(self, db):
        self.db=db
        self.slots=asyncio.Semaphore(2)
        self.pool=None

    async def get(self, gtins):
        pipeline(gtins)  # Bounds checked before acquiring or submitting work.
        await asyncio.wait_for(self.slots.acquire(),timeout=.05)
        if not _PROCESS_SLOTS.acquire(blocking=False):
            self.slots.release()
            raise TimeoutError('optional raw query capacity unavailable')
        loop=asyncio.get_running_loop()
        try:
            if self.pool is None:
                self.pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='mdlp-raw')
            database=self.db.delegate
            future=self.pool.submit(read_raw,database,gtins)
        except BaseException:
            _PROCESS_SLOTS.release()
            self.slots.release()
            raise
        def finished(actual_worker):
            _PROCESS_SLOTS.release()
            try:
                loop.call_soon_threadsafe(self.slots.release)
            except RuntimeError:
                pass  # Event loop closed: no further requests can acquire it.
        future.add_done_callback(finished)
        wrapped=asyncio.wrap_future(future)
        wrapped.add_done_callback(lambda f: None if f.cancelled() else f.exception())
        return await asyncio.wait_for(asyncio.shield(wrapped),timeout=RESOLVER_SECONDS)
