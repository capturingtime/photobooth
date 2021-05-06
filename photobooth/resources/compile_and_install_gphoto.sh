#!/bin/sh
# Compile GPhoto2 with libgphoto2 on RaspberryPi 4
# Based on guide: https://pimylifeup.com/raspberry-pi-dslr-camera-control/
# $ uname -a
#   Linux raspberrypi 5.10.17-v7l+ #1421 SMP Thu May 27 14:00:13 BST 2021 armv7l GNU/Linux
# $ cat /etc/os-release
#   PRETTY_NAME="Raspbian GNU/Linux 10 (buster)"
#   NAME="Raspbian GNU/Linux"
#   VERSION_ID="10"
#   VERSION="10 (buster)"
#   VERSION_CODENAME=buster
#   ID=raspbian
#   ID_LIKE=debian
#   HOME_URL="http://www.raspbian.org/"
#   SUPPORT_URL="http://www.raspbian.org/RaspbianForums"
#   BUG_REPORT_URL="http://www.raspbian.org/RaspbianBugs"

function stamp()
{
   echo $(date +%Y%m%dT%H%M%S%z)
}
echo "$(stamp) DEPLOYMENT SCRIPT (L${LINENO}): Make a working directory at $HOME/compile_gphoto"
cd $HOME && mkdir compile_gphoto && cd compile_gphoto

echo "$(stamp) DEPLOYMENT SCRIPT (L${LINENO}): Install dependencies"
sudo apt-get install -y -qq git make autoconf libltdl-dev libusb-dev libexif-dev libpopt-dev libxml2-dev libjpeg-dev libgd-dev gettext autopoint

echo "$(stamp) DEPLOYMENT SCRIPT (L${LINENO}): Download (git) libgphoto2 source"
git clone https://github.com/gphoto/libgphoto2.git

echo "$(stamp) DEPLOYMENT SCRIPT (L${LINENO}): Configure (libgphoto2)"
cd libgphoto2
autoreconf --install --symlink
./configure
echo "$(stamp) DEPLOYMENT SCRIPT (L${LINENO}): Make (libgphoto2)"
make
echo "$(stamp) DEPLOYMENT SCRIPT (L${LINENO}): Install (libgphoto2)"
sudo make install
echo "$(stamp) DEPLOYMENT SCRIPT (L${LINENO}): Compile and install complete (libgphoto2)"


echo "$(stamp) DEPLOYMENT SCRIPT (L${LINENO}): Download (git) gphoto2 source"
cd ../
git clone https://github.com/gphoto/gphoto2.git

echo "$(stamp) DEPLOYMENT SCRIPT (L${LINENO}): Configure (gphoto2)"
cd gphoto2
autoreconf --install --symlink
./configure
echo "$(stamp) DEPLOYMENT SCRIPT (L${LINENO}): Make (gphoto2)"
make
echo "$(stamp) DEPLOYMENT SCRIPT (L${LINENO}): Install (gphoto2)"
sudo make install
echo "$(stamp) DEPLOYMENT SCRIPT (L${LINENO}): Compile and install complete (gphoto2)"


