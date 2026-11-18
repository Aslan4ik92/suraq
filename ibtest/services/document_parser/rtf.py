"""Извлечение текста из RTF без внешних зависимостей.

Поддерживает \\uN (Unicode, в т.ч. казахские буквы), \\'hh в кодировке
\\ansicpg, вложенные группы и пропуск служебных групп (\\*, fonttbl,
colortbl, stylesheet, info, pict и т.п.).
"""
from __future__ import annotations

import re

_DESTINATIONS = {
    "aftncn", "aftnsep", "aftnsepc", "annotation", "atnauthor", "atndate", "atnicn", "atnid", "atnparent",
    "atnref", "atntime", "atrfend", "atrfstart", "author", "background", "bkmkend", "bkmkstart", "blipuid",
    "buptim", "category", "colorschememapping", "colortbl", "comment", "company", "creatim", "datafield",
    "datastore", "defchp", "defpap", "do", "doccomm", "docvar", "dptxbxtext", "ebcend", "ebcstart",
    "factoidname", "falt", "fchars", "ffdeftext", "ffentrymcr", "ffexitmcr", "ffformat", "ffhelptext",
    "ffl", "ffname", "ffstattext", "file", "filetbl", "fldinst", "fldtype", "fname", "fontemb", "fontfile",
    "fonttbl", "footer", "footerf", "footerl", "footerr", "footnote", "formfield", "ftncn", "ftnsep",
    "ftnsepc", "g", "generator", "gridtbl", "header", "headerf", "headerl", "headerr", "hl", "hlfr", "hlinkbase",
    "hlloc", "hlsrc", "hsv", "htmltag", "info", "keycode", "keywords", "latentstyles", "lchars", "levelnumbers",
    "leveltext", "lfolevel", "linkval", "list", "listlevel", "listname", "listoverride", "listoverridetable",
    "listpicture", "liststylename", "listtable", "listtext", "lsdlockedexcept", "macc", "maccPr", "mailmerge",
    "maln", "malnScr", "manager", "margPr", "mbar", "mbarPr", "mbaseJc", "mbegChr", "mborderBox", "mborderBoxPr",
    "mbox", "mboxPr", "mchr", "mcount", "mctrlPr", "md", "mdeg", "mdegHide", "mden", "mdiff", "mdPr", "me",
    "mendChr", "meqArr", "meqArrPr", "mf", "mfName", "mfPr", "mfunc", "mfuncPr", "mgroupChr", "mgroupChrPr",
    "mgrow", "mhideBot", "mhideLeft", "mhideRight", "mhideTop", "mhtmltag", "mlim", "mlimloc", "mlimlow",
    "mlimlowPr", "mlimupp", "mlimuppPr", "mm", "mmaddfieldname", "mmath", "mmathPict", "mmathPr", "mmaxdist",
    "mmc", "mmcJc", "mmconnectstr", "mmconnectstrdata", "mmcPr", "mmcs", "mmdatasource", "mmheadersource",
    "mmmailsubject", "mmodso", "mmodsofilter", "mmodsofldmpdata", "mmodsomappedname", "mmodsoname",
    "mmodsorecipdata", "mmodsosort", "mmodsosrc", "mmodsotable", "mmodsoudl", "mmodsoudldata",
    "mmodsouniquetag", "mmPr", "mmquery", "mmr", "mnary", "mnaryPr", "mnoBreak", "mnum", "mobjDist",
    "moMath", "moMathPara", "moMathParaPr", "mopEmu", "mphant", "mphantPr", "mplcHide", "mpos", "mr",
    "mrad", "mradPr", "mrPr", "msepChr", "mshow", "mshp", "msPre", "msPrePr", "msSub", "msSubPr", "msSubSup",
    "msSubSupPr", "msSup", "msSupPr", "mstrikeBLTR", "mstrikeH", "mstrikeTLBR", "mstrikeV", "msub", "msubHide",
    "msup", "msupHide", "mtransp", "mtype", "mvertJc", "mvfmf", "mvfml", "mvtof", "mvtol", "mzeroAsc",
    "mzeroDesc", "mzeroWid", "nesttableprops", "nextfile", "nonesttables", "objalias", "objclass", "objdata",
    "object", "objname", "objsect", "objtime", "oldcprops", "oldpprops", "oldsprops", "oldtprops",
    "oleclsid", "operator", "panose", "password", "passwordhash", "pgp", "pgptbl", "picprop", "pict", "pn",
    "pnseclvl", "pntext", "pntxta", "pntxtb", "printim", "private", "propname", "protend", "protstart",
    "protusertbl", "pxe", "result", "revtbl", "revtim", "rsidtbl", "rxe", "shp", "shpgrp", "shpinst",
    "shppict", "shprslt", "shptxt", "sn", "sp", "staticval", "stylesheet", "subject", "sv", "svb", "tc",
    "template", "themedata", "title", "txe", "ud", "upr", "userprops", "wgrffmtfilter", "windowcaption",
    "writereservation", "writereservhash", "xe", "xform", "xmlattrname", "xmlattrvalue", "xmlclose",
    "xmlname", "xmlnstbl", "xmlopen",
}

_SPECIAL = {
    "par": "\n", "sect": "\n\n", "page": "\n\n", "line": "\n", "tab": "\t", "emdash": "\u2014",
    "endash": "\u2013", "emspace": "\u2003", "enspace": "\u2002", "qmspace": "\u2005", "bullet": "\u2022",
    "lquote": "\u2018", "rquote": "\u2019", "ldblquote": "\u201C", "rdblquote": "\u201D", "row": "\n",
    "cell": " | ", "nestcell": " | ", "~": "\u00A0", "-": "", "_": "\u2011",
}

_PATTERN = re.compile(r"\\([a-z]{1,32})(-?\d{1,10})?[ ]?|\\'([0-9a-f]{2})|\\([^a-z])|([{}])|[\r\n]+|(.)",
                      re.I | re.S)


def rtf_to_text(rtf: str) -> str:
    stack: list[tuple[int, bool, str]] = []
    ignorable = False
    ucskip = 1
    curskip = 0
    codepage = "cp1251"
    out: list[str] = []
    m_cp = re.search(r"\\ansicpg(\d+)", rtf)
    if m_cp:
        codepage = f"cp{m_cp.group(1)}"
    pending: bytearray = bytearray()

    def flush():
        nonlocal pending
        if pending:
            try:
                out.append(pending.decode(codepage))
            except (UnicodeDecodeError, LookupError):
                out.append(pending.decode("cp1251", errors="replace"))
            pending = bytearray()

    for match in _PATTERN.finditer(rtf):
        word, arg, hexcode, char, brace, tchar = match.groups()
        if hexcode is None:
            flush()
        if brace:
            curskip = 0
            if brace == "{":
                stack.append((ucskip, ignorable, codepage))
            elif brace == "}" and stack:
                ucskip, ignorable, codepage = stack.pop()
        elif char:
            curskip = 0
            if char == "~":
                if not ignorable:
                    out.append("\u00A0")
            elif char in "{}\\":
                if not ignorable:
                    out.append(char)
            elif char == "*":
                ignorable = True
        elif word:
            curskip = 0
            if word in _DESTINATIONS:
                ignorable = True
            elif ignorable:
                pass
            elif word in _SPECIAL:
                out.append(_SPECIAL[word])
            elif word == "uc":
                ucskip = int(arg)
            elif word == "u":
                c = int(arg)
                if c < 0:
                    c += 0x10000
                out.append(chr(c))
                curskip = ucskip
        elif hexcode:
            if curskip > 0:
                curskip -= 1
            elif not ignorable:
                pending.append(int(hexcode, 16))
        elif tchar:
            if curskip > 0:
                curskip -= 1
            elif not ignorable:
                out.append(tchar)
    flush()
    return "".join(out)
