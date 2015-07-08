#!/bin/bash
set -e

HOME=/home/vagrant
DISTDIR=/repo/tmp/NuoDBAWSQuickstart/Linux
mkdir -p $DISTDIR

cd ${HOME}
for file in `find /repo/bin -type f`;
do
  echo "##### INSTALLING ${file}"
  pyinstaller --distpath=$DISTDIR --hidden-import=pkg_resources -F ${file}
  echo "##### CREATED ${DISTDIR}/$(basename $file)"
done

#rm /repo/tmp/*.tgz
#cp /tmp/installer.tgz /repo/tmp/${tarball}
#[ -L /repo/tmp/latest.tgz ] && rm /repo/tmp/latest.tgz
# ln -s /repo/tmp/${tarball} /repo/tmp/latest.tgz