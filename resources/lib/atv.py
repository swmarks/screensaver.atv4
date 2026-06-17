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

        # CoreELEC DV Luminance Hijack placeholders
        self.dv_setting_id = "coreelec.amlogic.dolbyvision.osd.brightness"
        self.original_dv_luminance = None

    def onInit(self):
        self.getControl(32502).setLabel(translate(32008))
        self.setProperty("screensaver-atv4-loading", "true")
        self.setProperty("show-info", addon.getSetting("show-info"))

        # Apply CoreELEC DV Luminance Hijack
        if addon.getSettingBool("enable-hdr") and addon.getSettingBool("show-info") and not addon.getSettingBool("ce-dv-follow"):
            target_luminance = addon.getSettingInt("ce-dv-brightness")
            try:
                resp = xbmc.executeJSONRPC(f'{{"jsonrpc":"2.0","method":"Settings.GetSettingValue","params":{{"setting":"{self.dv_setting_id}"}},"id":1}}')
                self.original_dv_luminance = json.loads(resp)['result']['value']
                
                if self.original_dv_luminance != target_luminance:
                    xbmc.executeJSONRPC(f'{{"jsonrpc":"2.0","method":"Settings.SetSettingValue","params":{{"setting":"{self.dv_setting_id}", "value": {target_luminance}}},"id":1}}')
                else:
                    self.original_dv_luminance = None 
            except Exception:
                pass

        if self.video_playlist:
            self.setProperty("screensaver-atv4-loading", "false")
            self.atv4player = xbmc.Player()

            threading.Thread(target=self.start_playback).start()

            self.max_allowed_time = None
            if self.isDPMSactive and addon.getSettingInt("check-dpms") == 1:
                self.max_allowed_time = self.DPMStime
            elif addon.getSettingInt("check-dpms") == 2:
                self.max_allowed_time = addon.getSettingInt("manual-dpms") * 60

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
        self.active = False
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
            except Exception:
                pass

        if addon.getSetting("toggle-cecoff") == "true":
            try:
                xbmc.executebuiltin('CECStandby')
            except Exception:
                pass

        if addon.getSettingBool("toggle-systemoff"):
            try:
                xbmc.executebuiltin('ShutDown')
            except Exception:
                pass

        if enable_window_placeholder:
            self.toTransparent()

    def novideos(self):
        self.setProperty("screensaver-atv4-loading", "false")
        self.getControl(32503).setLabel(translate(32048))
        self.getControl(32503).setVisible(True)

    @classmethod
    def toTransparent(self):
        trans = ScreensaverTrans('screensaver-atv4-trans.xml', addon_path, 'default', '')
        trans.doModal()
        xbmc.sleep(100)
        del trans

    def clearAll(self, close=True):
        self.active = False
        
        # Restore CoreELEC DV Luminance if hijacked
        if getattr(self, 'original_dv_luminance', None) is not None:
            try:
                xbmc.executeJSONRPC(f'{{"jsonrpc":"2.0","method":"Settings.SetSettingValue","params":{{"setting":"{self.dv_setting_id}", "value": {self.original_dv_luminance}}},"id":1}}')
            except Exception:
                pass
                
        if self.atv4player:
            self.atv4player.stop()
            
        self.close()

    def onAction(self, action):
        addon.setSettingBool("is_locked", False)
        self.clearAll()

    def start_playback(self):
        playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        playlist.clear()
        
        url_to_location = {}
        for video in self.video_playlist:
            url = video["url"]
            location = video["location"]
            list_item = xbmcgui.ListItem(location)
            playlist.add(url=url, listitem=list_item)
            url_to_location[url] = location

        self.atv4player.play(playlist, windowed=True)
        
        current_playing_url = None
        is_transitioning = True 
        
        while self.active and not monitor.abortRequested():
            monitor.waitForAbort(0.25)
            
            if self.active and self.atv4player.isPlaying():
                try:
                    total_time = self.atv4player.getTotalTime()
                    current_time = self.atv4player.getTime()
                    playing_url = self.atv4player.getPlayingFile()
                    
                    if playing_url != current_playing_url:
                        current_playing_url = playing_url
                        is_transitioning = True
                        new_location = url_to_location.get(playing_url, "")
                        self.setProperty('AerialLocation', new_location)
                    
                    if total_time > 0 and (total_time - current_time) <= 3:
                        is_transitioning = True
                        
                    elif is_transitioning and 0.5 <= current_time < 10.0:
                        is_transitioning = False

                    if is_transitioning:
                        self.setProperty("fade-black", "true")
                    else:
                        self.setProperty("fade-black", "false")
                        
                except Exception:
                    self.setProperty("fade-black", "true")
                    pass
                    
            elif self.active and not self.atv4player.isPlaying():
                self.setProperty("fade-black", "true")
                
                # Debounce: Wait up to 2 seconds to let Kodi natively load the next file
                recovery_ticks = 0
                while self.active and not self.atv4player.isPlaying() and recovery_ticks < 8:
                    monitor.waitForAbort(0.25)
                    recovery_ticks += 1
                
                # If it is STILL stopped after 2 seconds, the playlist naturally ended or network dropped
                if self.active and not self.atv4player.isPlaying():
                    self.atv4player.play(playlist, windowed=True)

def run(params=False):
    if not params:
        addon.setSettingBool("is_locked", True)
        screensaver = Screensaver('screensaver-atv4.xml', addon_path, 'default', '')
        screensaver.setProperty("fade-black", "true")
        screensaver.doModal()
        xbmc.sleep(100)
        del screensaver
    else:
        offline()
