# -*- coding: utf-8 -*-
# Copy URL - NVDA Global Plugin
# Copyright (C) 2026 Dennis Long
# Licensed under the GNU General Public License version 2 or later.
#
# Two commands:
#   1. Copy the URL of the current document/page.
#      Gesture: Alt+Control+Windows+C
#   2. Copy the URL of the link at the current browse-mode cursor position
#      (a "sub URL" - e.g. a link on the page you have not clicked).
#      Gesture: Alt+Control+Windows+L
#      This command can be turned off entirely in settings.
#
# Settings dialog (NVDA menu > Preferences > Settings > Copy URL) offers three
# fully independent options:
#   - Say "URL copied" before speaking the copied page URL.
#   - Enable/disable the Copy Link URL command itself.
#   - Say "Link URL copied" before speaking the copied link URL.
# The same panel turns the daily check for updates (updater.py) on or off.

import globalPluginHandler
import api
import ui
import config
import gui
import wx
import controlTypes
from gui import guiHelper
from gui.settingsDialogs import SettingsPanel
import addonHandler

from . import updater

addonHandler.initTranslation()

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
		via the tree interceptor's documentConstantIdentifier.
		"""
		url = None

		obj = api.getFocusObject()
		treeInterceptor = getattr(obj, "treeInterceptor", None)

		if treeInterceptor is None:
			foreground = api.getForegroundObject()
			treeInterceptor = getattr(foreground, "treeInterceptor", None)

		if treeInterceptor is not None:
			url = getattr(treeInterceptor, "documentConstantIdentifier", None)

		return url

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
		Find the URL of the link at (or containing) the current navigator object,
		i.e. wherever the browse-mode cursor currently is - without clicking it.
		"""
		obj = api.getNavigatorObject()
		current = obj
		# Walk a few levels up in case the cursor is on text inside the link
		# rather than on the link object itself.
		for _unused in range(4):
			if current is None:
				break
			if current.role == controlTypes.Role.LINK:
				url = self._getLinkURLFromObject(current)
				if url:
					return url
			current = current.parent
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
