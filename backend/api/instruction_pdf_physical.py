"""Bounded read-only physical PDF identity inputs, independent of publisher modes."""
import hashlib
import io
import os
from pathlib import Path
import re
import stat
import unicodedata
from .medication_instructions import _ru

_REGISTRATION = re.compile(r'(?<!\w)(?:ЛП|ЛСР|ЛС)\s*[-–]?\s*(?:№|No|N)?\s*\(?\d{4,8}\)?(?:\s*[-–]?\s*\(?(?:РГ|ГП)[-–](?:RU|KZ|BY|AM|KG)\)?)?(?:/\d{1,4})?|(?<!\w)[РП]\s*(?:No|N|№)\s*\d{4,8}(?:/\d{1,4})?',re.I)

def _physical_texts(path,proof,resources=False,raw_text=False):
    from pypdf import PdfReader
    from scripts.check_instruction_original_pdf import alternate_medical_heading,check_resources
    body=_bounded_bytes(path,proof['original_bytes'])
    if len(body)!=proof['original_bytes'] or hashlib.sha256(body).hexdigest()!=proof['original_sha256']:raise ValueError('physical original SHA/bytes differs')
    if not body.startswith(b'%PDF-') or b'%%EOF' not in body[-1024:]:raise ValueError('complete literal PDF framing required')
    reader=PdfReader(io.BytesIO(body),strict=True)
    if reader.is_encrypted or len(reader.pages)!=proof['page_count']:raise ValueError('physical page bounds differ')
    if resources:check_resources(reader)
    texts=[];total=0;first=''
    for page in reader.pages:
        stream=page.get_contents()
        if stream is not None and len(stream.get_data())>8*1024*1024:raise ValueError('physical content bound exceeded')
        text=page.extract_text() or '';total+=len(text)
        if not texts:first=text
        if len(text)>1024*1024 or total>16*1024*1024:raise ValueError('physical identity extraction bound exceeded')
        if re.search(r'проект|draft|project|proekt',text,re.I):raise ValueError('physical project/version context requires review')
        texts.append(text if raw_text else ' '.join(unicodedata.normalize('NFKC',text).split()))
    kind=('spc' if re.match(r'\s*общая\s+характеристика\s+лекарственного\s+препарата\s*(?:\n|$)',first[:12000],re.I)
        else 'patient_leaflet' if re.search(r'листок\s*[-–—]\s*вкладыш',first[:12000],re.I)
        else 'medical_instruction' if re.search(r'инструкци[яи]\s+по\s+медицинскому\s+применению',first[:12000],re.I)
        or alternate_medical_heading(first) else None)
    return texts,kind

def _registration_conflicts(texts,number):
    number=_ru(number)
    for text in texts:
        for match in _REGISTRATION.finditer(text):
            if _ru(match.group())!=number:raise ValueError('conflicting physical registration/country')

def _bounded_bytes(path,size):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size!=size:raise ValueError('physical size/type differs')
        data=bytearray()
        while len(data)<=size:
            block=os.read(fd,min(65536,size+1-len(data)))
            if not block:break
            data.extend(block)
        signature=lambda s:(s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink)
        if len(data)!=size or signature(before)!=signature(os.fstat(fd)) or signature(before)!=signature(Path(path).lstat()):
            raise ValueError('physical source changed during bounded read')
        return bytes(data)
    finally:os.close(fd)
