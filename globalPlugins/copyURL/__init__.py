# -*- coding: utf-8 -*-
# Copy URL - NVDA Global Plugin
# Copyright (C) 2026 Dennis Long
# Licensed under the MIT License.
#
# Two commands:
#   1. Copy the URL of the current document/page.
#      Gesture: Alt+Control+Windows+C
#   2. Copy the URL of the link at the current browse-mode cursor position
#      (a "sub URL" - e.g. a link on the page you have not clicked).
#      Gesture: Alt+Control+Windows+L
#      This command can be turned off entirely in settings.
#
# Both work whether NVDA reads the browser through IAccessible2 or through UI
# Automation (UIA browse mode, which Edge and other Chromium browsers can use).
#
# Settings dialog (NVDA menu > Preferences > Settings > Copy URL) offers three
# fully independent options:
#   - Say "URL copied" before speaking the copied page URL.
#   - Enable/disable the Copy Link URL command itself.
#   - Say "Link URL copied" before speaking the copied link URL.
# The same panel turns the daily check for updates (updater.py) on or off.

import re

import globalPluginHandler
import api
import ui
import config
import gui
import wx
import controlTypes
import textInfos
import treeInterceptorHandler
import winUser
from gui import guiHelper
from gui.settingsDialogs import SettingsPanel
import addonHandler
from logHandler import log

from . import updater

addonHandler.initTranslation()

try:
	ROLE_LINK = controlTypes.Role.LINK
except AttributeError:
	# NVDA 2021.1 and earlier.
	ROLE_LINK = controlTypes.ROLE_LINK
#: A URL starts with its scheme: https:, file:, about:, edge: and so on.
URL_START = re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]+:\S")
#: How many objects up from the cursor to look for the link it is in, as NVDA's own
#: "report link destination" command does: the cursor is often on text inside the link.
LINK_SEARCH_DEPTH = 10


def isURL(text):
	return isinstance(text, str) and URL_START.match(text) is not None


def tryGet(getter):
	"""Returns getter(), or None if NVDA can't get it, as happens when the page has just changed."""
	try:
		return getter()
	except Exception:
		log.debugWarning("Copy URL could not read the browser", exc_info=True)
		return None


confspec = {
	"announceCopiedPrefixPageURL": "boolean(default=true)",
	"announceCopiedPrefixLinkURL": "boolean(default=true)",
	"enableLinkURLCopy": "boolean(default=true)",
}
config.conf.spec["copyURL"] = confspec


class CopyURLSettingsPanel(SettingsPanel):
	# Translators: title of the Copy URL settings category in NVDA's Settings dialog.
	title = _("Copy URL")

	def makeSettings(self, settingsSizer):
		helper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

		helper.addItem(
			wx.StaticText(
				self,
				label=_(
					"To change the Copy page URL or Copy link URL shortcut, open "
					"NVDA menu > Preferences > Input Gestures, then find the Copy URL category."
				),
			)
		)

		self.announceCopiedPrefixPageURLCheckBox = helper.addItem(
			wx.CheckBox(
				self,
				# Translators: label of a checkbox in Copy URL's settings, for the
				# "copy page URL" command.
				label=_('Say "URL copied" before speaking the copied page URL'),
			)
		)
		self.announceCopiedPrefixPageURLCheckBox.SetValue(
			config.conf["copyURL"]["announceCopiedPrefixPageURL"]
		)

		self.enableLinkURLCopyCheckBox = helper.addItem(
			wx.CheckBox(
				self,
				# Translators: label of a checkbox in Copy URL's settings that turns
				# the Copy Link URL command on or off entirely.
				label=_("Enable the Copy Link URL command"),
			)
		)
		self.enableLinkURLCopyCheckBox.SetValue(
			config.conf["copyURL"]["enableLinkURLCopy"]
		)

		self.announceCopiedPrefixLinkURLCheckBox = helper.addItem(
			wx.CheckBox(
				self,
				# Translators: label of a checkbox in Copy URL's settings, for the
				# "copy link URL" (sub URL) command.
				label=_('Say "Link URL copied" before speaking the copied link URL'),
			)
		)
		self.announceCopiedPrefixLinkURLCheckBox.SetValue(
			config.conf["copyURL"]["announceCopiedPrefixLinkURL"]
		)

		self.updates = updater.SettingsControls(self, helper)

	def onSave(self):
		config.conf["copyURL"]["announceCopiedPrefixPageURL"] = (
			self.announceCopiedPrefixPageURLCheckBox.GetValue()
		)
		config.conf["copyURL"]["announceCopiedPrefixLinkURL"] = (
			self.announceCopiedPrefixLinkURLCheckBox.GetValue()
		)
		config.conf["copyURL"]["enableLinkURLCopy"] = (
			self.enableLinkURLCopyCheckBox.GetValue()
		)
		self.updates.save()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	"""Adds global commands to copy the current page URL, or a link's URL, to the clipboard."""

	def __init__(self):
		super().__init__()
		categoryClasses = gui.settingsDialogs.NVDASettingsDialog.categoryClasses
		if CopyURLSettingsPanel not in categoryClasses:
			categoryClasses.append(CopyURLSettingsPanel)
		updater.start()

	def terminate(self):
		updater.stop()
		categoryClasses = gui.settingsDialogs.NVDASettingsDialog.categoryClasses
		if CopyURLSettingsPanel in categoryClasses:
			categoryClasses.remove(CopyURLSettingsPanel)
		super().terminate()

	def _getCurrentURL(self):
		"""
		Find the URL of the document currently being read.
		Browse-mode documents (Firefox, Chrome, Edge, etc.) expose their URL
		through their tree interceptor.
		"""
		for treeInterceptor in self._getTreeInterceptors():
			url = self._getDocumentURL(treeInterceptor)
			if url:
				return url
		return None

	def _getTreeInterceptors(self):
		"""The browse-mode documents the user is most likely reading, nearest first."""
		found = []
		for getTreeInterceptor in (
			lambda: api.getFocusObject().treeInterceptor,
			lambda: api.getNavigatorObject().treeInterceptor,
			lambda: api.getForegroundObject().treeInterceptor,
			# Focus may be outside the page, in the address bar or on a toolbar.
			self._getDocumentShownInForeground,
		):
			treeInterceptor = tryGet(getTreeInterceptor)
			if treeInterceptor is not None and treeInterceptor not in found:
				found.append(treeInterceptor)
				yield treeInterceptor

	def _getDocumentURL(self, treeInterceptor):
		"""
		The URL of a browse-mode document, or None.
		Through IAccessible2 the URL is the documentConstantIdentifier. In UIA browse mode that is
		an automation ID such as "792", not a URL, and the URL is the document's own value, which
		NVDA 2025.1 and later also give as documentURL.
		"""
		for getURL in (
			lambda: treeInterceptor.documentURL,
			lambda: treeInterceptor.documentConstantIdentifier,
			lambda: treeInterceptor.rootNVDAObject.value,
		):
			url = tryGet(getURL)
			if isURL(url):
				return url
		return None

	def _getDocumentShownInForeground(self):
		"""
		The browse-mode document on screen in the foreground window, or None.
		Chromium browsers give each tab its own document window and hide it while the tab is in the
		background. Browsers that draw every tab in the main window, as Firefox does, can't be told
		apart this way, so their documents are left out.
		"""
		foregroundHandle = tryGet(lambda: api.getForegroundObject().windowHandle)
		if not foregroundHandle:
			return None
		shown = []
		for treeInterceptor in list(treeInterceptorHandler.runningTable):
			handle = tryGet(lambda: treeInterceptor.rootNVDAObject.windowHandle)
			if (
				handle
				and handle != foregroundHandle
				and winUser.isWindowVisible(handle)
				and winUser.getAncestor(handle, winUser.GA_ROOT) == foregroundHandle
			):
				shown.append(treeInterceptor)
		# Two at once (Edge's split screen, say) would be a guess.
		return shown[0] if len(shown) == 1 else None

	def _getLinkURLFromObject(self, obj):
		"""
		Try to pull a destination URL off a single NVDA object representing a link.
		Different browsers/toolkits expose it differently, so try a couple of routes.
		"""
		# For most IAccessible2-based links (Firefox, Chrome, Edge), the
		# accessible "value" of a link object is its destination URL.
		url = getattr(obj, "value", None)
		if url:
			return url

		# Some links instead expose the destination as an IAccessible2 attribute.
		ia2Attrs = getattr(obj, "IA2Attributes", None)
		if ia2Attrs:
			url = ia2Attrs.get("href")
			if url:
				return url

		return None

	def _getSubURL(self):
		"""
		Find the URL of the link at (or containing) the navigator object, the browse-mode
		cursor or the focus - without clicking it.
		The navigator object comes first, so a link reached with object navigation is copied.
		It follows the browse-mode cursor only while NVDA's review cursor follows the caret,
		so the cursor is asked next, then the focus, which is the link in focus mode.
		"""
		for getObject in (api.getNavigatorObject, self._getObjectAtCaret, api.getFocusObject):
			url = self._getLinkURLAround(tryGet(getObject))
			if url:
				return url
		return None

	def _getObjectAtCaret(self):
		"""The object at the browse-mode cursor, or None in focus mode."""
		treeInterceptor = api.getFocusObject().treeInterceptor
		if treeInterceptor is None or treeInterceptor.passThrough:
			return None
		info = treeInterceptor.makeTextInfo(textInfos.POSITION_CARET)
		info.expand(textInfos.UNIT_CHARACTER)
		return info.NVDAObjectAtStart

	def _getLinkURLAround(self, obj):
		"""The URL of the link obj is, or is inside: the cursor is often on the link's text, or on bold text in it."""
		for _unused in range(LINK_SEARCH_DEPTH):
			if obj is None:
				return None
			if tryGet(lambda: obj.role) == ROLE_LINK:
				url = tryGet(lambda: self._getLinkURLFromObject(obj))
				if url:
					return url
			obj = tryGet(lambda: obj.parent)
		return None

	def _announce(self, url, prefix, announcePrefixConfigKey):
		if api.copyToClip(url):
			if config.conf["copyURL"][announcePrefixConfigKey]:
				ui.message(prefix.format(url=url))
			else:
				ui.message(url)
		else:
			ui.message(_("Unable to copy URL to clipboard"))

	def script_copyURLToClipboard(self, gesture):
		url = self._getCurrentURL()
		if not url:
			ui.message(_("No URL found"))
			return
		# Translators: reported after the current page's URL has been copied to the clipboard.
		self._announce(url, _("URL copied: {url}"), "announceCopiedPrefixPageURL")

	# Translators: Message presented in input help mode.
	script_copyURLToClipboard.__doc__ = _(
		"Copies the URL of the current document to the clipboard and announces it"
	)
	# Translators: Category shown for this command in NVDA's Input Gestures dialog.
	script_copyURLToClipboard.category = _("Copy URL")

	def script_copySubURLToClipboard(self, gesture):
		if not config.conf["copyURL"]["enableLinkURLCopy"]:
			# Translators: reported when the user triggers Copy Link URL while it is disabled in settings.
			ui.message(_("Copy Link URL is disabled in Copy URL settings"))
			return
		url = self._getSubURL()
		if not url:
			ui.message(_("No link found"))
			return
		# Translators: reported after a link's URL has been copied to the clipboard.
		self._announce(url, _("Link URL copied: {url}"), "announceCopiedPrefixLinkURL")

	# Translators: Message presented in input help mode.
	script_copySubURLToClipboard.__doc__ = _(
		"Copies the URL of the link at the current browse mode cursor position, "
		"without clicking it, and announces it. Can be turned off in Copy URL settings"
	)
	# Translators: Category shown for this command in NVDA's Input Gestures dialog.
	script_copySubURLToClipboard.category = _("Copy URL")

	def script_checkForUpdates(self, gesture):
		updater.checkForUpdates()

	# Translators: Message presented in input help mode.
	script_checkForUpdates.__doc__ = _("Checks for Copy URL updates")
	# Translators: Category shown for this command in NVDA's Input Gestures dialog.
	script_checkForUpdates.category = _("Copy URL")

	# NVDA's Input Gestures dialog uses these defaults and stores any user
	# replacements in its own gesture map. This keeps custom assignments intact.
	__gestures = {
		"kb:alt+control+windows+c": "copyURLToClipboard",
		"kb:alt+control+windows+l": "copySubURLToClipboard",
	}
