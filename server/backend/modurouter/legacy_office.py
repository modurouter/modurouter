"""Bounded legacy Office conversion with macros, updates and network disabled."""

import ctypes
import errno
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree.ElementTree import ParseError

import olefile
from defusedxml import ElementTree as XML
from defusedxml.common import DefusedXmlException

from .document_formats import DOCX, PPTX, XLSX
from .office import office_text

DOC = "application/msword"
XLS = "application/vnd.ms-excel"
PPT = "application/vnd.ms-powerpoint"
ODT = "application/vnd.oasis.opendocument.text"
RTF = "application/rtf"
LEGACY_FORMATS = {".doc": DOC, ".xls": XLS, ".ppt": PPT, ".odt": ODT, ".rtf": RTF}
ERRORS = {
    "DOCUMENT_INVALID", "DOCUMENT_ENCRYPTED", "DOCUMENT_SIZE_LIMIT",
    "DOCUMENT_VERSION_UNSUPPORTED", "LEGACY_CONVERTER_UNAVAILABLE",
    "LEGACY_CONVERSION_FAILED", "LEGACY_CONVERSION_TIMEOUT",
}
MAX_INPUT = 10 * 1024**2
MAX_EXPANDED = 64 * 1024**2
MAX_MEMBER = 16 * 1024**2
CONVERSION_TIMEOUT = 40
_TARGETS = {
    DOC: ("docx", "Office Open XML Text", DOCX),
    ODT: ("docx", "Office Open XML Text", DOCX),
    RTF: ("docx", "Office Open XML Text", DOCX),
    XLS: ("xlsx", "Calc MS Excel 2007 XML", XLSX),
    PPT: ("pptx", "Impress MS PowerPoint 2007 XML", PPTX),
}


def _validate_odt(path: Path):
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = {item.filename for item in entries}
        if (len(entries) > 4096 or sum(item.file_size for item in entries) > MAX_EXPANDED
                or any(item.file_size > MAX_MEMBER for item in entries)):
            raise ValueError("DOCUMENT_SIZE_LIMIT")
        if len(names) != len(entries) or any(
            PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts for name in names
        ):
            raise ValueError("DOCUMENT_INVALID")
        if any(item.flag_bits & 1 for item in entries):
            raise ValueError("DOCUMENT_ENCRYPTED")
        if "mimetype" not in names or archive.read("mimetype").strip() != ODT.encode():
            raise ValueError("FILE_TYPE_MISMATCH")
        if "content.xml" not in names or "META-INF/manifest.xml" not in names:
            raise ValueError("DOCUMENT_INVALID")
        manifest = XML.fromstring(archive.read("META-INF/manifest.xml"), forbid_dtd=True)
        if any(node.tag.rsplit("}", 1)[-1] == "encryption-data" for node in manifest.iter()):
            raise ValueError("DOCUMENT_ENCRYPTED")
        XML.fromstring(archive.read("content.xml"), forbid_dtd=True)


def _validate_ole(path: Path, mime: str):
    if not olefile.isOleFile(path):
        raise ValueError("FILE_TYPE_MISMATCH")
    with olefile.OleFileIO(path, raise_defects=olefile.DEFECT_INCORRECT) as archive:
        if archive.exists("EncryptedPackage") or archive.exists("EncryptionInfo"):
            raise ValueError("DOCUMENT_ENCRYPTED")
        if mime == DOC:
            if not archive.exists("WordDocument"):
                raise ValueError("FILE_TYPE_MISMATCH")
            header = archive.openstream("WordDocument").read(32)
            if len(header) < 32 or header[:2] != b"\xec\xa5":
                raise ValueError("DOCUMENT_INVALID")
            version = struct.unpack_from("<H", header, 2)[0]
            flags = struct.unpack_from("<H", header, 10)[0]
            if flags & 0x0100:
                raise ValueError("DOCUMENT_ENCRYPTED")
            if version < 0x00C1:
                raise ValueError("DOCUMENT_VERSION_UNSUPPORTED")
            if not archive.exists("1Table" if flags & 0x0200 else "0Table"):
                raise ValueError("DOCUMENT_INVALID")
        elif mime == XLS:
            stream = "Workbook" if archive.exists("Workbook") else "Book"
            if not archive.exists(stream):
                raise ValueError("FILE_TYPE_MISMATCH")
            if archive.get_size(stream) > MAX_INPUT:
                raise ValueError("DOCUMENT_SIZE_LIMIT")
            data = archive.openstream(stream).read(MAX_INPUT + 1)
            offset = 0
            while offset + 4 <= len(data):
                record, size = struct.unpack_from("<HH", data, offset)
                if record == 0x002F:  # BIFF FILEPASS, before encrypted records.
                    raise ValueError("DOCUMENT_ENCRYPTED")
                if offset == 0 and record not in (0x0809, 0x0409, 0x0209):
                    raise ValueError("DOCUMENT_VERSION_UNSUPPORTED")
                offset += 4 + size
                if offset > len(data):
                    raise ValueError("DOCUMENT_INVALID")
                if record == 0x000A:
                    break
            if len(data) < 4:
                raise ValueError("DOCUMENT_INVALID")
        elif mime == PPT:
            if not archive.exists("PowerPoint Document"):
                raise ValueError("FILE_TYPE_MISMATCH")
            if not archive.exists("Current User"):
                raise ValueError("DOCUMENT_VERSION_UNSUPPORTED")
            header = archive.openstream("Current User").read(16)
            if len(header) < 16:
                raise ValueError("DOCUMENT_INVALID")
            token = struct.unpack_from("<I", header, 12)[0]
            if token == 0xF3D1C4DF:
                raise ValueError("DOCUMENT_ENCRYPTED")
            if token != 0xE391C05F:
                raise ValueError("DOCUMENT_INVALID")


def validate_legacy(path: Path, mime: str):
    if mime not in _TARGETS:
        raise ValueError("FILE_UNSUPPORTED")
    try:
        if path.stat().st_size > MAX_INPUT:
            raise ValueError("DOCUMENT_SIZE_LIMIT")
        if mime == ODT:
            _validate_odt(path)
        elif mime == RTF:
            with path.open("rb") as handle:
                if not handle.read(16).startswith(b"{\\rtf1"):
                    raise ValueError("FILE_TYPE_MISMATCH")
        else:
            _validate_ole(path, mime)
    except (OSError, zipfile.BadZipFile, KeyError, ParseError, DefusedXmlException,
            NotImplementedError, struct.error) as exc:
        raise ValueError("DOCUMENT_INVALID") from exc


class _SeccompArg(ctypes.Structure):
    _fields_ = [("arg", ctypes.c_uint), ("op", ctypes.c_uint),
                ("datum_a", ctypes.c_uint64), ("datum_b", ctypes.c_uint64)]


def _network_guard():
    """Return preexec hook; production conversion fails closed without seccomp."""
    if sys.platform != "linux":
        raise ValueError("LEGACY_CONVERTER_UNAVAILABLE")
    try:
        library = ctypes.CDLL("libseccomp.so.2", use_errno=True)
        library.seccomp_init.argtypes = [ctypes.c_uint32]
        library.seccomp_init.restype = ctypes.c_void_p
        library.seccomp_release.argtypes = [ctypes.c_void_p]
        library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
        library.seccomp_syscall_resolve_name.restype = ctypes.c_int
        library.seccomp_rule_add_array.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint, ctypes.POINTER(_SeccompArg),
        ]
        library.seccomp_rule_add_array.restype = ctypes.c_int
        library.seccomp_load.argtypes = [ctypes.c_void_p]
        library.seccomp_load.restype = ctypes.c_int
        socket_call = library.seccomp_syscall_resolve_name(b"socket")
        if socket_call < 0:
            raise OSError("socket syscall unavailable")
    except (OSError, AttributeError) as exc:
        raise ValueError("LEGACY_CONVERTER_UNAVAILABLE") from exc

    def apply():
        context = library.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
        if not context:
            raise OSError("seccomp initialization failed")
        try:
            # SCMP_CMP_NE permits AF_UNIX only, including the private UNO pipe.
            # close_fds=True also prevents inheritance of network descriptors.
            condition = _SeccompArg(0, 1, 1, 0)
            if library.seccomp_rule_add_array(
                context, 0x00050000 | errno.EACCES, socket_call, 1, ctypes.byref(condition)
            ) < 0 or library.seccomp_load(context) < 0:
                raise OSError("seccomp installation failed")
        finally:
            library.seccomp_release(context)
    return apply


_PROFILE = '''<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting">
<prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop>
<prop oor:name="DisableActiveContent" oor:op="fuse"><value>true</value></prop>
<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>
<prop oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value></prop>
</item>
<item oor:path="/org.openoffice.Office.Calc/Content/Update">
<prop oor:name="Link" oor:op="fuse"><value>1</value></prop>
</item>
<item oor:path="/org.openoffice.Office.Calc/Formula/Load">
<prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>1</value></prop>
<prop oor:name="ODFRecalcMode" oor:op="fuse"><value>1</value></prop>
</item></oor:items>'''

# NO_UPDATE and NEVER_EXECUTE are both 0 in the published UNO API.
# https://api.libreoffice.org/docs/idl/ref/namespacecom_1_1sun_1_1star_1_1document_1_1UpdateDocMode.html
_UNO_SCRIPT = r'''
import sys, time
try:
    import uno, unohelper
    from com.sun.star.task import XInteractionHandler
except ImportError:
    sys.exit(5)

def prop(name, value):
    item = uno.createUnoStruct("com.sun.star.beans.PropertyValue")
    item.Name, item.Value = name, value
    return item

class AbortInteraction(unohelper.Base, XInteractionHandler):
    def handle(self, request):
        for continuation in request.getContinuations():
            abort = continuation.queryInterface(uno.getTypeByName("com.sun.star.task.XInteractionAbort"))
            if abort:
                abort.select()
                break

local = uno.getComponentContext()
resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
deadline = time.monotonic() + 12
while True:
    try:
        context = resolver.resolve("uno:pipe,name=" + sys.argv[1] + ";urp;StarOffice.ComponentContext")
        break
    except Exception:
        if time.monotonic() >= deadline:
            sys.exit(4)
        time.sleep(0.1)
desktop = context.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", context)
document = None
try:
    document = desktop.loadComponentFromURL(uno.systemPathToFileUrl(sys.argv[2]), "_blank", 0, (
        prop("Hidden", True), prop("ReadOnly", True), prop("Silent", True),
        prop("MacroExecutionMode", 0), prop("UpdateDocMode", 0),
        prop("InteractionHandler", AbortInteraction()), prop("Password", ""),
    ))
    if document is None:
        sys.exit(3)
    document.storeToURL(uno.systemPathToFileUrl(sys.argv[3]), (
        prop("FilterName", sys.argv[4]), prop("Overwrite", True),
        prop("InteractionHandler", AbortInteraction()),
    ))
finally:
    if document is not None:
        document.close(True)
    desktop.terminate()
'''


def _convert(source: Path, output: Path, filter_name: str, directory: Path):
    executable = shutil.which("soffice") or shutil.which("libreoffice")
    system_python = Path("/usr/bin/python3")
    if not executable or not system_python.is_file():
        raise ValueError("LEGACY_CONVERTER_UNAVAILABLE")
    binary = Path(executable).resolve().with_name("soffice.bin")
    if binary.is_file():
        executable = str(binary)
    guard = _network_guard()
    profile = directory / "profile"
    (profile / "user").mkdir(parents=True)
    (profile / "user" / "registrymodifications.xcu").write_text(_PROFILE, encoding="utf-8")
    environment = {
        "PATH": "/usr/bin:/bin", "HOME": str(directory), "TMPDIR": str(directory),
        "XDG_CONFIG_HOME": str(directory / "config"), "XDG_CACHE_HOME": str(directory / "cache"),
        "LANG": "C.UTF-8", "SAL_USE_VCLPLUGIN": "svp", "OMP_NUM_THREADS": "1",
    }
    pipe = "modurouter_" + uuid.uuid4().hex
    office_args = [
        executable, "-env:UserInstallation=" + profile.as_uri(), "--headless", "--nologo",
        "--nodefault", "--norestore", "--nolockcheck", "--nofirststartwizard",
        "--accept=pipe,name=" + pipe + ";urp;StarOffice.ComponentContext",
    ]
    options = dict(
        cwd=directory, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True, preexec_fn=guard,
    )
    process = helper = None
    try:
        process = subprocess.Popen(office_args, **options)
        helper = subprocess.Popen(
            [str(system_python), "-c", _UNO_SCRIPT, pipe, str(source), str(output), filter_name],
            **options,
        )
        deadline = time.monotonic() + CONVERSION_TIMEOUT
        restarts = 0
        while helper.poll() is None:
            if time.monotonic() >= deadline:
                raise ValueError("LEGACY_CONVERSION_TIMEOUT")
            office_status = process.poll()
            # The direct binary asks its launcher to restart after initializing a
            # fresh profile. Avoid the launcher so all child PIDs stay owned here.
            if office_status == 81 and restarts < 2:
                restarts += 1
                process = subprocess.Popen(office_args, **options)
            elif office_status is not None:
                # Normal termination follows desktop.terminate() in the helper.
                if office_status != 0:
                    raise ValueError("LEGACY_CONVERTER_UNAVAILABLE")
            time.sleep(0.05)
        if helper.returncode in (4, 5):
            raise ValueError("LEGACY_CONVERTER_UNAVAILABLE")
        if helper.returncode or not output.is_file():
            raise ValueError("LEGACY_CONVERSION_FAILED")
        if output.stat().st_size > MAX_INPUT:
            raise ValueError("DOCUMENT_SIZE_LIMIT")
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("LEGACY_CONVERTER_UNAVAILABLE") from exc
    finally:
        for child in (helper, process):
            if child is not None:
                child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=2)


def legacy_text(path: Path, mime: str) -> str:
    validate_legacy(path, mime)
    extension = next(extension for extension, value in LEGACY_FORMATS.items() if value == mime)
    target, filter_name, output_mime = _TARGETS[mime]
    with tempfile.TemporaryDirectory(prefix="modurouter-office-") as temporary:
        directory = Path(temporary)
        source = directory / ("input" + extension)
        shutil.copyfile(path, source)
        source.chmod(0o600)
        output = directory / ("converted." + target)
        _convert(source, output, filter_name, directory)
        text = office_text(output, output_mime)
    if not text.strip():
        raise ValueError("NO_EXTRACTABLE_TEXT")
    notice = "[구형/호환 문서 변환: 배치나 일부 개체가 달라질 수 있습니다. 매크로, 외부 연결과 포함 개체는 실행하지 않습니다.]\n"
    if mime == XLS:
        notice += "[XLS 수식 결과는 변환 시점 값이며 원본에 저장된 값과 다를 수 있습니다.]\n"
    return notice + text
