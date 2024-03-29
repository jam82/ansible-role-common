#!/usr/bin/python

# The MIT License (MIT)
#
# Copyright (c) 2014 Austin Hyde
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

import os
import pwd
import platform
from ansible.module_utils.basic import AnsibleModule


def cower_in_path(module):
    """
    Determine if cower is available.
    """
    rc, stdout, stderr = module.run_command('which cower', check_rc=False)
    return rc == 0


def pacman_in_path(module):
    """
    Determine if pacman is available.
    """
    rc, stdout, stderr = module.run_command('which pacman', check_rc=False)
    return rc == 0


def package_installed(module, pkg):
    """
    Determine if a package is already installed.
    """
    rc, stdout, stderr = module.run_command(
        'pacman -Q %s' % pkg, check_rc=False)
    return rc == 0


def check_packages(module, pkgs):
    """
    Inform the user what would change if the module were run.
    """
    would_be_changed = []

    for pkg in pkgs:
        installed = package_installed(module, pkg)
        if not installed:
            would_be_changed.append(pkg)

    if would_be_changed:
        module.exit_json(changed=True, msg='%s package(s) would be installed' % (len(would_be_changed)))
    else:
        module.exit_json(changed=False, msg='all packages are already installed')


def download_packages(module, pkgs, dir, user):
    """
    Download the specified packages.
    """
    # Use cower, if available.
    if cower_in_path(module):
        cmds = ['sudo -u %s cower -dqf %s', ]
    # Otherwise, fall back to cURL
    else:
        cmds = ['sudo -u %s curl -O https://aur.archlinux.org/cgit/aur.git/snapshot/%s.tar.gz',
                'sudo -u %s tar xzf %s.tar.gz']
    for pkg in pkgs:
        # If the package is already installed, skip the download.
        if package_installed(module, pkg):
            continue
        # Change into the specified directory for download.
        os.chdir(dir)
        # Attempt to install the package.
        for cmd in cmds:
            rc, stdout, stderr = module.run_command(cmd % (user, pkg), check_rc=False)
            if rc != 0:
                module.fail_json(msg='failed to download package %s, because: %s' % (pkg, stderr))


def install_packages(module, pkgs, dir, user, virtual):
    """
    Install the specified packages via makepkg.
    """
    num_installed = 0

    if platform.machine().startswith('arm') or platform.machine().startswith('aarch64'):
        makepkg_args = '-Acsrf'
    else:
        makepkg_args = '-csrf'
    cmd = 'sudo -u %s PKGEXT=".pkg.tar" makepkg %s --noconfirm --needed --noprogressbar' % (user, makepkg_args)
    if module.params['skip_pgp']:
        cmd += ' --skippgpcheck'
    for pkg in pkgs:
        # If the package is already installed, skip the install.
        if package_installed(module, pkg):
            continue

        # Change into the package directory.
        # Check if the package is a virtual package
        if virtual:
            os.chdir(os.path.join(dir, virtual))
        else:
            os.chdir(os.path.join(dir, pkg))

        # Attempt to build the directory.
        rc, stdout, stderr = module.run_command(cmd, check_rc=False)
        if rc != 0:
            module.fail_json(msg='failed to build package %s, because: %s' % (pkg, stderr))

        # If the package was succesfully built, install it.
        rc, stdout, stderr = module.run_command('pacman -U --noconfirm *.pkg.tar*', check_rc=False, use_unsafe_shell=True)
        if rc != 0:
            module.fail_json(msg='failed to install package %s, because: %s' % (pkg, stderr))
        else:
            num_installed += 1

    # Exit with the number of packages succesfully installed.
    if num_installed > 0:
        module.exit_json(changed=True, msg='installed %s package(s)' % num_installed)
    else:
        module.exit_json(changed=False, msg='all packages were already installed')


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(required=True, type='list'),
            user=dict(required=True),
            dir=dict(),
            skip_pgp=dict(default=False, type='bool'),
            virtual=dict(),
        ),
        supports_check_mode=True
    )

    # Fail of pacman is not available.
    if not pacman_in_path(module):
        module.fail_json(msg="could not locate pacman executable")

    p = module.params

    # Get all the requested package names.
    pkgs = p['name']

    # Fail if the specified user does not exist.
    try:
        pwd.getpwnam(p['user'])
    except KeyError:
        module.fail_json(msg="user %s does not exist" % p['user'])
    else:
        user = p['user']

    # If no directory was given, assume the packages should be downloaded to
    # ~user/aur.
    if not p['dir']:
        home = os.path.expanduser('~%s' % user)
        if not os.path.exists(home):
            module.fail_json(msg="%s's home directory %s does not exist" % (user, home))

        dir = os.path.join(home, 'aur')
        if not os.path.exists(dir):
            os.makedirs(dir)
            uid = pwd.getpwnam(user).pw_uid
            os.chown(dir, uid, -1)
    else:
        dir = os.path.expanduser(p['dir'])

    # Fail if the specified directory does not exist.
    if not os.path.exists(dir):
        module.fail_json(msg="directory %s does not exist" % dir)

    if module.check_mode:
        check_packages(module, pkgs)

    download_packages(module, pkgs, dir, user)
    # Check if the package is virtual
    if p['virtual']:
        virtual = p['virtual']
    else:
        virtual = False

    install_packages(module, pkgs, dir, user, virtual)


main()
