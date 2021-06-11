#!/bin/sh
xset -dpms     # disable DPMS (Energy Star) features.
xset s off     # disable screen saver
xset s noblank # don't blank the video device
matchbox-window-manager -use_titlebar no &
unclutter &    # hide X mouse cursor unless mouse activated
chromium-browser --kiosk --start-maximized --no-sandbox --display=:0.0 --incognito --window-size=1920,1080 --window-position=0,0 http://127.0.0.1:8000/main/
