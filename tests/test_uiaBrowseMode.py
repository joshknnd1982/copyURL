"""Copy URL's commands in UIA browse mode and through IAccessible2, run outside NVDA.

python -m unittest discover -s tests

In UIA browse mode (Edge and other Chromium browsers read through UI Automation),
NVDA's documentConstantIdentifier is the automation ID of the window around the
page, such as "792", so Copy URL 1.9.3 said "No URL found" or copied that number.
The page's URL is the document's UIA value, which NVDA 2025.1 and later also give
as documentURL. The NVDA code these tests run is NVDA's own, word for word: the
tree interceptors of NVDAObjects/UIA/chromium.py and virtualBuffers/gecko_ia2.py
and the UIA value properties of NVDAObjects/UIA/__init__.py. The page values are
what a real Edge page gives through UI Automation.

Set NVDA_SOURCE to the source folder of NVDA 2026.2 to check that the NVDA code
here is still NVDA's. Set COPYURL_LIVE_EDGE=1 to read a real Edge page through UI
Automation as well: that opens an Edge window with a throwaway profile for a few
seconds, then closes it.
"""

import __future__

import ast
import builtins
import ctypes
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import types
import unittest
from ctypes import wintypes
from enum import Enum

from _ctypes import COMError

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PACKAGE = "globalPlugins.copyURL"

# -- NVDA's own code ----------------------------------------------------------------------------

#: NVDA 2026.2, NVDAObjects/UIA/chromium.py. NVDA 2024.4 has the same class without _get_documentURL.
CHROMIUM_TREE_INTERCEPTOR = """\
class ChromiumUIATreeInterceptor(web.UIAWebTreeInterceptor):
	def _get_documentConstantIdentifier(self):
		return self.rootNVDAObject.parent._getUIACacheablePropertyValue(UIAHandler.UIA_AutomationIdPropertyId)

	def _get_documentURL(self) -> str | None:
		return self.rootNVDAObject.value"""

#: NVDA 2026.2, NVDAObjects/UIA/__init__.py, class UIA.
UIA_VALUE = (
	"""\
def _get_UIAValue(self) -> typing.Optional[str]:
	val = self._getUIACacheablePropertyValue(UIAHandler.UIA.UIA_ValueValuePropertyId, True)
	if val != UIAHandler.handler.reservedNotSupportedValue:
		return val
	return None""",
	"""\
def _get_UIARangeValue(self) -> typing.Optional[float]:
	val = self._getUIACacheablePropertyValue(UIAHandler.UIA.UIA_RangeValueValuePropertyId, True)
	if val != UIAHandler.handler.reservedNotSupportedValue:
		return val
	return None""",
	"""\
def _get_value(self) -> typing.Optional[str]:
	if self.UIAValue is not None:
		return self.UIAValue
	if self.UIARangeValue is not None:
		return f"{round(self.UIARangeValue)}"
	return None""",
)

#: NVDA 2026.2, virtualBuffers/gecko_ia2.py, class Gecko_ia2 (Firefox, and Chrome through IAccessible2).
GECKO_DOCUMENT = (
	"""\
def _get_documentURL(self) -> str:
	return self.documentConstantIdentifier""",
	"""\
def _get_documentConstantIdentifier(self):
	try:
		return self.rootNVDAObject.IAccessibleObject.accValue(0)
	except COMError:
		return None""",
)

#: Copy URL 1.9.3's page lookup, to show what went wrong.
COPY_URL_1_9_3 = """\
def _getCurrentURL(self):
	url = None

	obj = api.getFocusObject()
	treeInterceptor = getattr(obj, "treeInterceptor", None)

	if treeInterceptor is None:
		foreground = api.getForegroundObject()
		treeInterceptor = getattr(foreground, "treeInterceptor", None)

	if treeInterceptor is not None:
		url = getattr(treeInterceptor, "documentConstantIdentifier", None)

	return url"""


def withoutMethod(classSource, name):
	"""classSource with one method removed: NVDA 2024.4's Chromium tree interceptor is 2026.2's without documentURL."""
	tree = ast.parse(classSource)
	tree.body[0].body = [node for node in tree.body[0].body if getattr(node, "name", None) != name]
	return ast.unparse(tree)


def compileNvdaCode(source):
	# NVDA's annotations use newer syntax; like NVDA's own, they are never evaluated.
	return compile(source, "<NVDA>", "exec", flags=__future__.annotations.compiler_flag, dont_inherit=True)


# -- what NVDA provides around that code ------------------------------------------------------


class AutoPropertyType(type):
	"""NVDA's baseObject.AutoPropertyType, reduced to what is used here: _get_x makes a property x."""

	def __init__(cls, name, bases, namespace):
		super().__init__(name, bases, namespace)
		for key, value in list(namespace.items()):
			if key.startswith("_get_"):
				setattr(cls, key[len("_get_"):], property(value))


class AutoPropertyObject(metaclass=AutoPropertyType):
	pass


class UIAHandlerStandIn(object):
	"""The UIAHandler names the NVDA code above uses; the IDs are UI Automation's own."""

	UIA_AutomationIdPropertyId = 30011
	UIA = types.SimpleNamespace(UIA_ValueValuePropertyId = 30045, UIA_RangeValueValuePropertyId = 30047)
	handler = types.SimpleNamespace(reservedNotSupportedValue=object())


UIAHandler = UIAHandlerStandIn


class Role(Enum):
	"""The controlTypes.Role members used here."""

	DOCUMENT = "document"
	PANE = "pane"
	LINK = "link"
	STATICTEXT = "text"
	STRONG = "strong"
	SECTION = "section"
	PARAGRAPH = "paragraph"
	EDITABLETEXT = "edit"
	GRAPHIC = "graphic"


class NVDAObject(AutoPropertyObject):
	"""The NVDAObject properties Copy URL reads."""

	def __init__(self, role=None, parent=None, windowHandle=None, treeInterceptor=None, value=None):
		self._role = role
		self._parent = parent
		self._windowHandle = windowHandle
		self.treeInterceptor = treeInterceptor
		self._value = value

	def _get_role(self):
		return self._role

	def _get_parent(self):
		return self._parent

	def _get_windowHandle(self):
		if self._windowHandle is None and self.parent is not None:
			return self.parent.windowHandle
		return self._windowHandle

	def _get_value(self):
		return self._value


class UIAObjectBase(NVDAObject):
	"""A UIA element: an automation ID and, if it has the Value pattern, a value."""

	def __init__(self, automationId="", uiaValue=None, **kwargs):
		super().__init__(**kwargs)
		self.properties = {UIAHandler.UIA_AutomationIdPropertyId: automationId}
		if uiaValue is not None:
			self.properties[UIAHandler.UIA.UIA_ValueValuePropertyId] = uiaValue

	def _getUIACacheablePropertyValue(self, ID, ignoreDefault=False):
		if ID in self.properties:
			return self.properties[ID]
		return UIAHandler.handler.reservedNotSupportedValue if ignoreDefault else ""


def nvdaMethods(sources, namespace):
	methods = {}
	for source in sources:
		exec(compileNvdaCode(source), namespace, methods)
	return methods


NVDA_NAMES = {"UIAHandler": UIAHandler, "typing": __import__("typing"), "COMError": COMError}
UIAObject = AutoPropertyType("UIA", (UIAObjectBase,), nvdaMethods(UIA_VALUE, NVDA_NAMES))


class FakeTextInfo(object):
	def __init__(self, obj):
		self.obj = obj
		self.expandedTo = None

	def expand(self, unit):
		self.expandedTo = unit

	@property
	def NVDAObjectAtStart(self):
		assert self.expandedTo == "character", "NVDA's link destination command expands to the character first"
		return self.obj


class BrowseModeDocument(AutoPropertyObject):
	"""What Copy URL uses of NVDA's BrowseModeDocumentTreeInterceptor."""

	#: browseMode.BrowseModeTreeInterceptor: documentURL: str | None = None
	documentURL = None

	def __init__(self, rootNVDAObject, caret=None, passThrough=False):
		self.rootNVDAObject = rootNVDAObject
		self.caret = caret
		self.passThrough = passThrough

	def _get_documentConstantIdentifier(self):
		return None

	def makeTextInfo(self, position):
		assert position == "caret"
		return FakeTextInfo(self.caret)


def nvdaClass(source, base, name):
	namespace = dict(NVDA_NAMES, web=types.SimpleNamespace(UIAWebTreeInterceptor=base))
	exec(compileNvdaCode(source), namespace)
	return namespace[name]


ChromiumUIATreeInterceptor = nvdaClass(CHROMIUM_TREE_INTERCEPTOR, BrowseModeDocument, "ChromiumUIATreeInterceptor")
ChromiumUIATreeInterceptor2024 = nvdaClass(
	withoutMethod(CHROMIUM_TREE_INTERCEPTOR, "_get_documentURL"), BrowseModeDocument, "ChromiumUIATreeInterceptor"
)
Gecko_ia2 = AutoPropertyType("Gecko_ia2", (BrowseModeDocument,), nvdaMethods(GECKO_DOCUMENT, NVDA_NAMES))


class IAccessible(object):
	def __init__(self, value):
		self._value = value

	def accValue(self, childID):
		if isinstance(self._value, Exception):
			raise self._value
		return self._value


class Dead(NVDAObject):
	"""An object whose page has gone: every property NVDA asks raises COMError."""

	def __getattribute__(self, name):
		if name in ("role", "parent", "value", "windowHandle", "treeInterceptor", "IA2Attributes"):
			raise COMError(-2147220991, "An event was unable to invoke any of the subscribers", (None,) * 5)
		return super().__getattribute__(name)


class Nvda(object):
	"""NVDA's state as Copy URL sees it: focus, navigator, foreground, windows, speech, clipboard."""

	def __init__(self):
		self.focus = None
		self.navigator = None
		self.foreground = NVDAObject(role=Role.PANE, windowHandle=0x100)
		self.windows = {}
		self.running = []
		self.spoken = []
		self.clipboard = None
		self.settings = {
			"announceCopiedPrefixPageURL": True,
			"announceCopiedPrefixLinkURL": True,
			"enableLinkURLCopy": True,
		}

	def copyToClip(self, text, notify=False):
		self.clipboard = text
		return True


class SettingsPanel(object):
	pass


class ConfigStandIn(object):
	def __init__(self, settings):
		self.spec = {}
		self.settings = settings

	def __getitem__(self, section):
		assert section == "copyURL"
		return self.settings


def loadPlugin(nvda, controlTypes=None):
	"""Imports Copy URL's global plugin against stand-ins for the NVDA modules it uses."""
	modules = {}

	def module(name, **attributes):
		modules[name] = types.ModuleType(name)
		modules[name].__dict__.update(attributes)
		return modules[name]

	module("globalPluginHandler", GlobalPlugin=type("GlobalPlugin", (object,), {"terminate": lambda self: None}))
	module(
		"api",
		getFocusObject=lambda: nvda.focus,
		getNavigatorObject=lambda: nvda.navigator,
		getForegroundObject=lambda: nvda.foreground,
		copyToClip=nvda.copyToClip,
	)
	module("ui", message=nvda.spoken.append)
	module("config", conf=ConfigStandIn(nvda.settings))
	module("gui")
	module("gui.guiHelper")
	module("gui.settingsDialogs", SettingsPanel=SettingsPanel, NVDASettingsDialog=types.SimpleNamespace(categoryClasses=[]))
	modules["gui"].guiHelper = modules["gui.guiHelper"]
	modules["gui"].settingsDialogs = modules["gui.settingsDialogs"]
	if controlTypes is None:
		module("controlTypes", Role=Role)
	else:
		modules["controlTypes"] = controlTypes
	module("textInfos", POSITION_CARET="caret", UNIT_CHARACTER="character")
	module("treeInterceptorHandler", runningTable=nvda.running)
	module(
		"winUser",
		GA_ROOT=2,
		isWindowVisible=lambda hwnd: nvda.windows[hwnd][0],
		getAncestor=lambda hwnd, flags: nvda.windows[hwnd][1] if flags == 2 else None,
	)
	module("addonHandler", initTranslation=lambda: setattr(builtins, "_", lambda text: text))
	module("logHandler", log=types.SimpleNamespace(debugWarning=lambda *args, **kwargs: None))
	module(PACKAGE + ".updater")
	globalPlugins = module("globalPlugins")
	globalPlugins.__path__ = [os.path.join(REPO, "globalPlugins")]

	for name in [name for name in sys.modules if name == "globalPlugins" or name.startswith("globalPlugins.")]:
		del sys.modules[name]
	saved = {name: sys.modules.get(name) for name in modules}
	sys.modules.update(modules)
	try:
		plugin = importlib.import_module(PACKAGE)
	finally:
		for name, previous in saved.items():
			if previous is None:
				sys.modules.pop(name, None)
			else:
				sys.modules[name] = previous
		sys.modules.pop(PACKAGE, None)
	return plugin


# -- the page -----------------------------------------------------------------------------------

#: What UI Automation gives for a page in Edge: the document's value is its URL, its parent is the
#: "Chrome Legacy Window" pane whose automation ID is a number, and each link's value is its URL.
PAGE_URL = "https://example.com/news/today.html?edition=1"
PAGE_PANE_ID = "792"
LINK_URL = "https://example.com/target?a=1&b=2#frag"


class Page(object):
	"""An Edge tab read through UI Automation, with a link whose text is partly bold."""

	def __init__(self, nvda, window=0x201, visible=True, url=PAGE_URL, interceptorClass=None):
		nvda.windows[window] = (visible, nvda.foreground.windowHandle)
		self.pane = UIAObject(role=Role.PANE, automationId=PAGE_PANE_ID, windowHandle=window)
		self.document = UIAObject(role=Role.DOCUMENT, automationId="RootWebArea", uiaValue=url, parent=self.pane)
		self.treeInterceptor = (interceptorClass or ChromiumUIATreeInterceptor)(self.document)
		self.document.treeInterceptor = self.treeInterceptor
		self.paragraph = self.inPage(Role.PARAGRAPH, self.document)
		self.text = self.inPage(Role.STATICTEXT, self.paragraph)
		self.link = self.inPage(Role.LINK, self.paragraph, uiaValue=LINK_URL)
		self.bold = self.inPage(Role.STRONG, self.link)
		self.boldText = self.inPage(Role.STATICTEXT, self.bold)
		self.treeInterceptor.caret = self.text
		nvda.running.append(self.treeInterceptor)

	def inPage(self, role, parent, **kwargs):
		return UIAObject(role=role, parent=parent, treeInterceptor=self.treeInterceptor, **kwargs)


class CopyURLTestCase(unittest.TestCase):
	def setUp(self):
		self.nvda = Nvda()
		self.plugin = loadPlugin(self.nvda)
		self.commands = self.plugin.GlobalPlugin.__new__(self.plugin.GlobalPlugin)

	def copyPageURL(self):
		self.commands.script_copyURLToClipboard(None)
		return self.nvda.spoken[-1]

	def copyLinkURL(self):
		self.commands.script_copySubURLToClipboard(None)
		return self.nvda.spoken[-1]

	def readPage(self, page):
		"""Browse mode on the page's plain text, the navigator following the cursor."""
		self.nvda.focus = page.document
		self.nvda.navigator = page.text
		page.treeInterceptor.caret = page.text


class PageURLTests(CopyURLTestCase):
	def test_uiaBrowseMode(self):
		page = Page(self.nvda)
		self.readPage(page)
		self.assertEqual(self.copyPageURL(), "URL copied: " + PAGE_URL)
		self.assertEqual(self.nvda.clipboard, PAGE_URL)

	def test_whatWentWrongIn1_9_3(self):
		page = Page(self.nvda)
		self.readPage(page)
		self.assertEqual(page.treeInterceptor.documentConstantIdentifier, PAGE_PANE_ID)
		self.assertEqual(page.treeInterceptor.documentURL, PAGE_URL)
		namespace = {
			"api": types.SimpleNamespace(
				getFocusObject=lambda: self.nvda.focus, getForegroundObject=lambda: self.nvda.foreground
			),
		}
		exec(COPY_URL_1_9_3, namespace)
		self.assertEqual(namespace["_getCurrentURL"](None), PAGE_PANE_ID)

	def test_uiaBrowseModeBeforeNVDA2025_1(self):
		page = Page(self.nvda, interceptorClass=ChromiumUIATreeInterceptor2024)
		self.readPage(page)
		self.assertIsNone(page.treeInterceptor.documentURL, "no documentURL before NVDA 2025.1")
		self.assertEqual(self.copyPageURL(), "URL copied: " + PAGE_URL)

	def test_withoutPrefix(self):
		self.nvda.settings["announceCopiedPrefixPageURL"] = False
		self.readPage(Page(self.nvda))
		self.assertEqual(self.copyPageURL(), PAGE_URL)

	def test_focusModeInAFormField(self):
		page = Page(self.nvda)
		page.treeInterceptor.passThrough = True
		self.nvda.focus = self.nvda.navigator = page.inPage(Role.EDITABLETEXT, page.paragraph)
		self.assertEqual(self.copyPageURL(), "URL copied: " + PAGE_URL)

	def test_iAccessible2(self):
		root = NVDAObject(role=Role.DOCUMENT, windowHandle=0x201, value=PAGE_URL)
		root.IAccessibleObject = IAccessible(PAGE_URL)
		treeInterceptor = Gecko_ia2(root)
		self.nvda.focus = self.nvda.navigator = NVDAObject(role=Role.LINK, parent=root, treeInterceptor=treeInterceptor)
		self.assertEqual(self.copyPageURL(), "URL copied: " + PAGE_URL)

	def test_iAccessible2PageGone(self):
		root = NVDAObject(role=Role.DOCUMENT, windowHandle=0x100)
		root.IAccessibleObject = IAccessible(COMError(-2147467259, "Unspecified error", (None,) * 5))
		self.nvda.focus = NVDAObject(parent=root, treeInterceptor=Gecko_ia2(root))
		self.assertEqual(self.copyPageURL(), "No URL found")

	def test_theAutomationIdIsNeverCopied(self):
		page = Page(self.nvda, url="")
		self.readPage(page)
		self.assertEqual(self.copyPageURL(), "No URL found")
		self.assertIsNone(self.nvda.clipboard)

	def test_focusInTheAddressBar(self):
		Page(self.nvda, window=0x202, visible=False, url="https://example.com/background-tab")
		Page(self.nvda, window=0x201)
		self.nvda.focus = self.nvda.navigator = NVDAObject(role=Role.EDITABLETEXT, windowHandle=0x100)
		self.assertEqual(self.copyPageURL(), "URL copied: " + PAGE_URL)

	def test_focusInTheAddressBarWithTwoTabsShown(self):
		Page(self.nvda, window=0x202, url="https://example.com/split-screen")
		Page(self.nvda, window=0x201)
		self.nvda.focus = self.nvda.navigator = NVDAObject(role=Role.EDITABLETEXT, windowHandle=0x100)
		self.assertEqual(self.copyPageURL(), "No URL found")

	def test_focusInTheAddressBarOfABrowserWithOneWindow(self):
		"""Firefox draws every tab in its main window, so a background tab can't be told from the one shown."""
		root = NVDAObject(role=Role.DOCUMENT, windowHandle=0x100)
		root.IAccessibleObject = IAccessible("https://example.com/background-tab")
		self.nvda.running.append(Gecko_ia2(root))
		self.nvda.windows[0x100] = (True, 0x100)
		self.nvda.focus = self.nvda.navigator = NVDAObject(role=Role.EDITABLETEXT, windowHandle=0x100)
		self.assertEqual(self.copyPageURL(), "No URL found")

	def test_notInABrowser(self):
		self.nvda.focus = self.nvda.navigator = NVDAObject(role=Role.EDITABLETEXT, windowHandle=0x100)
		self.assertEqual(self.copyPageURL(), "No URL found")

	def test_pageGone(self):
		page = Page(self.nvda)
		self.nvda.focus = self.nvda.navigator = Dead()
		page.document.properties[UIAHandler.UIA.UIA_ValueValuePropertyId] = ""
		self.assertEqual(self.copyPageURL(), "No URL found")


class LinkURLTests(CopyURLTestCase):
	def test_onTheLinkText(self):
		page = Page(self.nvda)
		self.readPage(page)
		self.nvda.navigator = page.treeInterceptor.caret = page.boldText
		self.assertEqual(self.copyLinkURL(), "Link URL copied: " + LINK_URL)
		self.assertEqual(self.nvda.clipboard, LINK_URL)

	def test_deepInsideTheLink(self):
		"""Copy URL 1.9.3 looked only 3 objects up."""
		page = Page(self.nvda)
		self.readPage(page)
		inner = page.bold
		for role in (Role.SECTION, Role.SECTION, Role.STRONG, Role.STATICTEXT):
			inner = page.inPage(role, inner)
		self.nvda.navigator = page.treeInterceptor.caret = inner
		self.assertEqual(self.copyLinkURL(), "Link URL copied: " + LINK_URL)

	def test_navigatorLeftBehind(self):
		"""With "Follow caret" off in Review Cursor settings, the navigator stays where it was."""
		page = Page(self.nvda)
		self.readPage(page)
		page.treeInterceptor.caret = page.boldText
		self.assertEqual(self.copyLinkURL(), "Link URL copied: " + LINK_URL)

	def test_objectNavigationComesFirst(self):
		page = Page(self.nvda)
		self.readPage(page)
		other = page.inPage(Role.LINK, page.paragraph, uiaValue="https://example.com/other")
		page.treeInterceptor.caret = page.boldText
		self.nvda.navigator = other
		self.assertEqual(self.copyLinkURL(), "Link URL copied: https://example.com/other")

	def test_focusMode(self):
		page = Page(self.nvda)
		page.treeInterceptor.passThrough = True
		page.treeInterceptor.caret = page.text
		self.nvda.focus = page.link
		self.nvda.navigator = page.text
		self.assertEqual(self.copyLinkURL(), "Link URL copied: " + LINK_URL)

	def test_iAccessible2Href(self):
		link = NVDAObject(role=Role.LINK, value="")
		link.IA2Attributes = {"href": LINK_URL}
		self.nvda.focus = self.nvda.navigator = NVDAObject(role=Role.STATICTEXT, parent=link)
		self.assertEqual(self.copyLinkURL(), "Link URL copied: " + LINK_URL)

	def test_noLink(self):
		page = Page(self.nvda)
		self.readPage(page)
		self.assertEqual(self.copyLinkURL(), "No link found")
		self.assertIsNone(self.nvda.clipboard)

	def test_linkWithoutADestination(self):
		page = Page(self.nvda)
		self.readPage(page)
		page.link.properties[UIAHandler.UIA.UIA_ValueValuePropertyId] = ""
		self.nvda.navigator = page.treeInterceptor.caret = page.boldText
		self.assertEqual(self.copyLinkURL(), "No link found")

	def test_navigatorGone(self):
		page = Page(self.nvda)
		self.readPage(page)
		self.nvda.navigator = Dead()
		page.treeInterceptor.caret = page.boldText
		self.assertEqual(self.copyLinkURL(), "Link URL copied: " + LINK_URL)

	def test_turnedOff(self):
		self.nvda.settings["enableLinkURLCopy"] = False
		self.readPage(Page(self.nvda))
		self.assertEqual(self.copyLinkURL(), "Copy Link URL is disabled in Copy URL settings")


class OlderNVDATests(unittest.TestCase):
	def test_roleLinkBeforeNVDA2021_2(self):
		nvda = Nvda()
		plugin = loadPlugin(nvda, controlTypes=types.SimpleNamespace(ROLE_LINK=Role.LINK))
		self.assertIs(plugin.ROLE_LINK, Role.LINK)


@unittest.skipUnless(os.environ.get("NVDA_SOURCE"), "set NVDA_SOURCE to NVDA 2026.2's source folder")
class NvdasOwnCodeTests(unittest.TestCase):
	def nvdaSource(self, path, className, methodName=None):
		with open(os.path.join(os.environ["NVDA_SOURCE"], *path.split("/")), encoding="utf-8") as f:
			source = f.read()
		for node in ast.walk(ast.parse(source)):
			if isinstance(node, ast.ClassDef) and node.name == className:
				if methodName is None:
					return ast.get_source_segment(source, node)
				for item in node.body:
					if getattr(item, "name", None) == methodName:
						return textwrap.dedent("\t" + ast.get_source_segment(source, item))
		raise LookupError(methodName or className)

	def test_chromium(self):
		self.assertEqual(
			self.nvdaSource("NVDAObjects/UIA/chromium.py", "ChromiumUIATreeInterceptor"), CHROMIUM_TREE_INTERCEPTOR
		)

	def test_uiaValue(self):
		for source in UIA_VALUE:
			name = source.split("(")[0][len("def "):]
			self.assertEqual(self.nvdaSource("NVDAObjects/UIA/__init__.py", "UIA", name), source)

	def test_gecko(self):
		for source in GECKO_DOCUMENT:
			name = source.split("(")[0][len("def "):]
			self.assertEqual(self.nvdaSource("virtualBuffers/gecko_ia2.py", "Gecko_ia2", name), source)

	def test_names(self):
		with open(os.path.join(os.environ["NVDA_SOURCE"], "textInfos", "__init__.py"), encoding="utf-8") as f:
			textInfos = f.read()
		self.assertIn('\nPOSITION_CARET = "caret"\n', textInfos)
		self.assertIn('\nUNIT_CHARACTER = "character"\n', textInfos)
		with open(os.path.join(os.environ["NVDA_SOURCE"], "winUser.py"), encoding="utf-8") as f:
			self.assertIn("\nGA_ROOT = 2\n", f.read())


# -- a real Edge page ---------------------------------------------------------------------------

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
LIVE_PAGE = """<!doctype html>
<html><head><title>Copy URL live test</title></head>
<body>
<h1>Copy URL live test</h1>
<p>Before <a href="https://example.com/target?a=1&amp;b=2#frag"><strong>bold inside</strong> link</a> after.</p>
<iframe src="frame.html" title="inner frame"></iframe>
</body></html>
"""
LIVE_FRAME = """<!doctype html><html><head><title>Inner</title></head>
<body><p><a href="https://example.org/inframe">frame link</a></p></body></html>
"""


@unittest.skipUnless(os.environ.get("COPYURL_LIVE_EDGE"), "set COPYURL_LIVE_EDGE=1 to read a real Edge page")
class LiveEdgeTests(CopyURLTestCase):
	"""NVDA's code and Copy URL's, on a real Edge page read through UI Automation."""

	@classmethod
	def setUpClass(cls):
		import comtypes.client

		comtypes.client.GetModule("UIAutomationCore.dll")
		from comtypes.gen import UIAutomationClient

		cls.U = UIAutomationClient
		cls.uia = comtypes.client.CreateObject(UIAutomationClient.CUIAutomation, interface=UIAutomationClient.IUIAutomation)
		cls.folder = tempfile.mkdtemp(prefix="copyURL-live-")
		for name, text in (("page.html", LIVE_PAGE), ("frame.html", LIVE_FRAME)):
			with open(os.path.join(cls.folder, name), "w", encoding="utf-8") as f:
				f.write(text)
		cls.pageURL = "file:///" + os.path.join(cls.folder, "page.html").replace("\\", "/")
		cls.edge = subprocess.Popen([
			EDGE, "--user-data-dir=" + os.path.join(cls.folder, "profile"), "--no-first-run",
			"--no-default-browser-check", "--new-window", cls.pageURL,
		])
		cls.window = None
		for _unused in range(60):
			cls.window = cls.findWindow("Copy URL live test")
			if cls.window:
				break
			time.sleep(0.5)
		time.sleep(2)

	@classmethod
	def tearDownClass(cls):
		subprocess.run(["taskkill", "/T", "/F", "/PID", str(cls.edge.pid)], capture_output=True)
		time.sleep(1)
		shutil.rmtree(cls.folder, ignore_errors=True)

	@staticmethod
	def findWindow(title):
		found = []
		user32 = ctypes.windll.user32

		@ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
		def visit(hwnd, _lParam):
			buffer = ctypes.create_unicode_buffer(512)
			user32.GetWindowTextW(hwnd, buffer, 512)
			if title in buffer.value and user32.IsWindowVisible(hwnd):
				found.append(hwnd)
			return True

		user32.EnumWindows(visit, 0)
		return found[0] if found else None

	def setUp(self):
		super().setUp()
		self.assertTrue(self.window, "Edge opened the page")
		U = self.U
		self.assertEqual(
			(U.UIA_AutomationIdPropertyId, U.UIA_ValueValuePropertyId, U.UIA_RangeValueValuePropertyId),
			(UIAHandler.UIA_AutomationIdPropertyId, UIAHandler.UIA.UIA_ValueValuePropertyId, UIAHandler.UIA.UIA_RangeValueValuePropertyId),
		)
		self.savedNotSupported = UIAHandler.handler.reservedNotSupportedValue
		UIAHandler.handler.reservedNotSupportedValue = self.uia.ReservedNotSupportedValue
		user32 = ctypes.windll.user32
		user32.GetAncestor.restype = wintypes.HWND
		winUser = types.SimpleNamespace(
			GA_ROOT=2,
			isWindowVisible=lambda hwnd: bool(user32.IsWindowVisible(hwnd)),
			getAncestor=lambda hwnd, flags: user32.GetAncestor(hwnd, flags),
		)
		self.plugin.winUser = winUser
		self.nvda.foreground = NVDAObject(role=Role.PANE, windowHandle=self.window)

	def tearDown(self):
		UIAHandler.handler.reservedNotSupportedValue = self.savedNotSupported

	def live(self, element, treeInterceptor=None):
		"""An NVDA UIA object for a real element, with NVDA's own value properties."""
		U = self.U
		test = self
		roles = {
			U.UIA_DocumentControlTypeId: Role.DOCUMENT,
			U.UIA_HyperlinkControlTypeId: Role.LINK,
			U.UIA_TextControlTypeId: Role.STATICTEXT,
			U.UIA_PaneControlTypeId: Role.PANE,
		}

		class LiveUIA(UIAObject):
			def _getUIACacheablePropertyValue(self, ID, ignoreDefault=False):
				return element.GetCurrentPropertyValueEx(ID, ignoreDefault)

			def _get_role(self):
				return roles.get(element.CurrentControlType, Role.SECTION)

			def _get_parent(self):
				parent = test.uia.RawViewWalker.GetParentElement(element)
				return test.live(parent, treeInterceptor) if parent else None

			def _get_windowHandle(self):
				handle = element.CurrentNativeWindowHandle
				return handle if handle else self.parent.windowHandle

		return LiveUIA(treeInterceptor=treeInterceptor)

	def find(self, controlType, name=None):
		U = self.U
		condition = self.uia.CreatePropertyCondition(U.UIA_ControlTypePropertyId, controlType)
		if name is not None:
			condition = self.uia.CreateAndCondition(
				condition, self.uia.CreatePropertyCondition(U.UIA_NamePropertyId, name)
			)
		# NVDA walks the raw view, and Chromium leaves text out of the control view.
		rawView = self.uia.CreateCacheRequest()
		rawView.TreeFilter = self.uia.RawViewCondition
		element = self.uia.ElementFromHandle(self.window).FindFirstBuildCache(U.TreeScope_Descendants, condition, rawView)
		self.assertTrue(element, "found %s %r" % (controlType, name))
		return element

	def liveDocument(self, interceptorClass=ChromiumUIATreeInterceptor):
		documentElement = self.find(self.U.UIA_DocumentControlTypeId, "Copy URL live test")
		treeInterceptor = interceptorClass(None)
		treeInterceptor.rootNVDAObject = self.live(documentElement, treeInterceptor)
		return treeInterceptor

	def test_pageURL(self):
		for interceptorClass in (ChromiumUIATreeInterceptor, ChromiumUIATreeInterceptor2024):
			with self.subTest(interceptorClass=interceptorClass):
				treeInterceptor = self.liveDocument(interceptorClass)
				identifier = treeInterceptor.documentConstantIdentifier
				self.assertNotEqual(identifier, self.pageURL, "the automation ID, not the URL")
				self.nvda.focus = self.nvda.navigator = treeInterceptor.rootNVDAObject
				self.assertEqual(self.copyPageURL(), "URL copied: " + self.pageURL)

	def test_pageURLFromTheAddressBar(self):
		treeInterceptor = self.liveDocument()
		self.nvda.running.append(treeInterceptor)
		self.nvda.focus = self.nvda.navigator = self.live(self.find(self.U.UIA_EditControlTypeId, "Address and search bar"))
		self.assertEqual(self.copyPageURL(), "URL copied: " + self.pageURL)

	def test_linkURL(self):
		treeInterceptor = self.liveDocument()
		boldText = self.live(self.find(self.U.UIA_TextControlTypeId, "bold inside"), treeInterceptor)
		self.nvda.focus = treeInterceptor.rootNVDAObject
		self.nvda.navigator = treeInterceptor.caret = boldText
		self.assertEqual(self.copyLinkURL(), "Link URL copied: https://example.com/target?a=1&b=2#frag")

	def test_linkInAFrame(self):
		treeInterceptor = self.liveDocument()
		frameText = self.live(self.find(self.U.UIA_TextControlTypeId, "frame link"), treeInterceptor)
		self.nvda.focus = treeInterceptor.rootNVDAObject
		self.nvda.navigator = treeInterceptor.caret = frameText
		self.assertEqual(self.copyLinkURL(), "Link URL copied: https://example.org/inframe")
		self.assertEqual(self.copyPageURL(), "URL copied: " + self.pageURL, "the page's URL, not the frame's")


if __name__ == "__main__":
	unittest.main(verbosity=2)
