"""
   Copyright (C) 2015- enen92
   This file is part of screensaver.atv4 - https://github.com/enen92/screensaver.atv4

   SPDX-License-Identifier: GPL-2.0-only
   See LICENSE for more information.
"""

import json
import threading

import xbmc
import xbmcgui

from .commonatv import translate, addon, addon_path
from .offline import offline
from .playlist import AtvPlaylist
from .trans import ScreensaverTrans

monitor = xbmc.Monitor()


class Screensaver(xbmcgui.WindowXML):

    def __init__(self, *args, **kwargs):
        self.DPMStime = json.loads(xbmc.executeJSONRPC(
            '{"jsonrpc":"2.0","method":"Settings.GetSettingValue","params":{"setting":"powermanagement.displaysoff"},"id":2}'))[
                            'result']['value'] * 60
        self.isDPMSactive = bool(self.DPMStime > 0)
        self.active = True
        self.atv4player = None
        self.video_playlist = AtvPlaylist().compute_playlist_array()
        xbmc.log(msg=f"kodi dpms time: {self.DPMStime}", level=xbmc.LOGDEBUG)
        xbmc.log(msg=f"kodi dpms active: {self.isDPMSactive}", level=xbmc.LOGDEBUG)

    def onInit(self):
        self.getControl(32502).setLabel(translate(32008))
        self.setProperty("screensaver-atv4-loading", "true")

        if self.video_playlist:
            self.setProperty("screensaver-atv4-loading", "false")
            self.atv4player = xbmc.Player()

            # Start player thread
            threading.Thread(target=self.start_playback).start()

            # DPMS logic
            self.max_allowed_time = None

            if self.isDPMSactive and addon.getSettingInt("check-dpms") == 1:
                self.max_allowed_time = self.DPMStime

            elif addon.getSettingInt("check-dpms") == 2:
                self.max_allowed_time = addon.getSettingInt("manual-dpms") * 60

            xbmc.log(msg=f"check dpms: {addon.getSetting('check-dpms')}",
                     level=xbmc.LOGDEBUG)
            xbmc.log(msg=f"before supervision: {self.max_allowed_time}",
                     level=xbmc.LOGDEBUG)

            if self.max_allowed_time:
                delta = 0
                while self.active:
                    if delta >= self.max_allowed_time:
                        self.activateDPMS()
                        break
                    monitor.waitForAbort(1)
                    delta += 1
        else:
            self.novideos()

    def activateDPMS(self):
        xbmc.log(msg="[Aerial Screensaver] Manually activating DPMS!", level=xbmc.LOGDEBUG)
        self.active = False

        # Take action on the video
        enable_window_placeholder = False
        if addon.getSettingInt("dpms-action") == 0:
            if self.atv4player:
                self.atv4player.pause()
        else:
            self.clearAll()
            enable_window_placeholder = True

        if addon.getSettingBool("toggle-displayoff") or addon.getSetting("toggle-cecoff") == "true" or addon.getSettingBool("toggle-systemoff"):
            monitor.waitForAbort(1)

        if addon.getSettingBool("toggle-displayoff"):
            try:
                xbmc.executebuiltin('ToggleDPMS')
            except Exception as e:
                xbmc.log(msg=f"[Aerial Screensaver] Failed to toggle DPMS: {e}",
                         level=xbmc.LOGDEBUG)

        if addon.getSetting("toggle-cecoff") == "true":
            try:
                xbmc.executebuiltin('CECStandby')
            except Exception as e:
                xbmc.log(msg=f"[Aerial Screensaver] Failed to toggle device off via CEC: {e}",
                         level=xbmc.LOGDEBUG)

        if addon.getSettingBool("toggle-systemoff"):
            try:
                xbmc.log(msg="[Aerial Screensaver] Triggering full system power down.", level=xbmc.LOGDEBUG)
                xbmc.executebuiltin('ShutDown')
            except Exception as e:
                xbmc.log(msg=f"[Aerial Screensaver] Failed to shut down system: {e}",
                         level=xbmc.LOGDEBUG)

        # Enable placeholder window
        if enable_window_placeholder:
            self.toTransparent()

    def novideos(self):
        self.setProperty("screensaver-atv4-loading", "false")
        self.getControl(32503).setLabel(translate(32048))
        self.getControl(32503).setVisible(True)

    @classmethod
    def toTransparent(self):
        trans = ScreensaverTrans(
            'screensaver-atv4-trans.xml',
            addon_path,
            'default',
            '',
        )
        trans.doModal()
        xbmc.sleep(100)
        del trans

    def clearAll(self, close=True):
        self.active = False
        if self.atv4player:
            self.atv4player.stop()
        self.close()

    def onAction(self, action):
        addon.setSettingBool("is_locked", False)
        self.clearAll()

    def start_playback(self):
        # 1. Setup the native Kodi Playlist
        playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        playlist.clear()
        
        # We need a quick dictionary to map URLs back to Locations for our polling loop
        url_to_location = {}
        
        # Populate the Kodi playlist with our array
        for video in self.video_playlist:
            url = video["url"]
            location = video["location"]
            
            # Create a basic ListItem so Kodi knows what it is handling
            list_item = xbmcgui.ListItem(location)
            playlist.add(url=url, listitem=list_item)
            
            # Store the mapping for the text overlay
            url_to_location[url] = location

        # 2. Command Kodi to play the entire playlist at once
        self.atv4player.play(playlist, windowed=True)
        
        current_playing_url = None
        
        # 3. Monitor loop to update the text and handle looping
        while self.active and not monitor.abortRequested():
            monitor.waitForAbort(1)
            
            if self.active and self.atv4player.isPlaying():
                try:
                    # Ask Kodi what specific URL is currently rendering
                    playing_url = self.atv4player.getPlayingFile()
                    
                    # If the URL changed since the last second, update the overlay!
                    if playing_url != current_playing_url:
                        current_playing_url = playing_url
                        new_location = url_to_location.get(playing_url, "")
                        self.setProperty('AerialLocation', new_location)
                except Exception:
                    # getPlayingFile() can occasionally throw an error exactly during a gapless transition
                    pass
                    
            # If the entire playlist reaches the very end, start it over
            elif self.active and not self.atv4player.isPlaying():
                self.atv4player.play(playlist, windowed=True)

def run(params=False):
    if not params:
        addon.setSettingBool("is_locked", True)
        screensaver = Screensaver(
            'screensaver-atv4.xml',
            addon_path,
            'default',
            '',
        )
        screensaver.doModal()
        xbmc.sleep(100)
        del screensaver

    else:
        # Params existed or was true when calling run(), so download files locally
        offline()
