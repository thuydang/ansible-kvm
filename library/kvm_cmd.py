#!/usr/bin/python
# -*- coding: utf-8 -*-

# (c) 2015, Chris Long <alcamie@gmail.com> <chlong@redhat.com>
#
# This file is a module for Ansible that interacts with Network Manager
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.    See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.    If not, see <http://www.gnu.org/licenses/>.


DOCUMENTATION='''
---
module: kvm_cmd
author: Thuy Dang
short_description: Create KVM VMs in specifiled folder and manage them using bash commands. No libvirtd!
requirements: [ qemu-kvm ]
description:
    - Manage KVM VMs. Create, start, stop, etc.
options:
    state:
        required: False
        default: "present"
        choices: [ present, absent ]
        description:
            - Whether the guest vm should exist or not, taking action if the state is different from what is stated.
    action:
        required: False
        default: None
        choices: [ create, show, up, down, remove ]
        description:
            - Set to 'create' to create a vm.
            - Set to 'remove' to delete a vm. The vm to be deleted is identified by its name 'instance_name'.
            - Set to 'show' to show a vm. Will show all vm if no 'instance_name' is set.
            - Set to 'up' to bring a vm up. Requires 'instance_name' to be set.
            - Set to 'down' to shutdown a vm. Requires 'instance_name' to be set.
    instance_name:
        required: True
        default: None
        description:
            - Where VMNAME will be the name used to id the vm. when not provided a default name is generated: <vm>[-<date>][-<time>]
'''

EXAMPLES='''
The following examples are working examples
We realize operations of OpenStack nova: https://access.redhat.com/documentation/en-US/Red_Hat_Enterprise_Linux_OpenStack_Platform/5/html/End_User_Guide/app_cheat_sheet.html

### Image Services (glance)

List images you can access  
    $ glance image-list

Delete specified image  
    $ glance image-delete IMAGE

Describe a specific image   
    $ glance image-show IMAGE
    $ ansible_src/ansible/hacking/test-module -m ansible_quicklabs/library_ext/ansible-kvm/library/kvm_cmd.py -a "action='image-show' image_name='/mnt/nfv/kvm_openstack_lab/images/cirros-0.3.4-x86_64-disk.img'"

Update image    
    $ glance image-update IMAGE

Kernel image    
    $ glance image-create --name "cirros-threepart-kernel" \
            --disk-format aki --container-format aki --is-public True \
            --file ~/images/cirros-0.3.1~pre4-x86_64-vmlinuz

RAM image     
    $ glance image-create -—name "cirros-threepart-ramdisk" \
            --disk-format ari --container-format ari --is-public True \
            --file ~/images/cirros-0.3.1~pre4-x86_64-initrd

Three-part image    
    $ glance image-create --name "cirros-threepart" --disk-format ami \
            --container-format ami --is-public True \
            --property kernel_id=$KID—property ramdisk_id=$RID \
            --file ~/images/cirros-0.3.1~pre4-x86_64-blank.img

Register raw image   
    $ glance image-create --name "cirros-qcow2" --disk-format qcow2 \
            --container-format bare --is-public True \
            --file ~/images/cirros-0.3.1~pre4-x86_64-disk.img

### Compute Services (nova)

Show details of instance
    $ show INSTANCE_NAME
    $ show MyFirstInstance

List instances, notice status of instance
    $ nova list

List images
    $ nova image-list

List flavors
    $ nova flavor-list

Create an instance from based image
    $ sudo ansible_src/ansible/hacking/test-module -m ansible_quicklabs/library_ext/ansible-kvm/library/kvm_cmd.py -a "action='instance-create' image_base='/mnt/nfv/kvm_openstack_lab/images/cirros-0.3.4-x86_64-disk.img' image_format='qcow2' instance_name='/mnt/nfv/kvm_openstack_lab/instances/controller.qcow2' image_size=200"

Boot an instance using flavor and image names (if names are unique)
    $ sudo ansible_src/ansible/hacking/test-module -m ansible_quicklabs/library_ext/ansible-kvm/library/kvm_cmd.py -a "action='boot' instance_name='/mnt/nfv/kvm_openstack_lab/instances/controller.qcow2' instance_cpus=1 instance_ram=1024 instance_vnc=:1 instance_cdrom=/mnt/nfv/kvm_openstack_lab/cloud-init/default/default-cidata.iso"
    $ nova boot --image IMAGE --nic net-id=NETWORKID \
    --flavor FLAVOR INSTANCE_NAME
    $ nova boot --image cirros-0.3.1-x86_64-uec \
        -nic net-id=3d706957-7696-4aa8-973f-b80892ff9a95 \
        --flavor m1.tiny MyFirstInstance
'''
# import ansible.module_utils.basic
import os
import syslog
import sys
import dbus
#from gi.repository import NetworkManager, NMClient


class KvmCmd(object):
    """
    This is the generic kvm class that is subclassed based on platform.
    A subclass may wish to override the following action methods:
            - up_connection()
            - down_connection()
    All subclasses MUST define platform and distribution (which may be None).
    """

    platform='Generic'
    distribution=None
    bus=dbus.SystemBus()
    # The following is going to be used in dbus code
    DEVTYPES={1: "Ethernet",
                       15: "Team"
                }
    STATES={0: "Unknown",
                 10: "Unmanaged",
                100: "Activated",
                 110: "Deactivating",
                 120: "Failed"
            }

    def __new__(cls, *args, **kwargs):
        return load_platform_subclass(KvmCmd, args, kwargs)

    def __init__(self, module):
        self.module=module
        self.action=module.params['action']
        self.state=module.params['state']
        self.instance_name=module.params['instance_name']
        self.instance_cpu=module.params['instance_cpu'] #cpu model: core2duo,+vmx
        self.instance_cpus=module.params['instance_cpus'] #numbers of core
        self.instance_ram=module.params['instance_ram']
        self.instance_vnc=module.params['instance_vnc']
        self.instance_display=module.params['instance_display']
        self.instance_cdrom=module.params['instance_cdrom']
        self.image_name=module.params['image_name']
        self.image_base=module.params['image_base']
        self.image_format=module.params['image_format']
        self.image_size=module.params['image_size']
        # dump additional debug info through syslog
        self.syslogging=True

    def execute_command(self, cmd, use_unsafe_shell=False, data=None):
        if self.syslogging:
            syslog.openlog('ansible-%s' % os.path.basename(__file__))
            syslog.syslog(syslog.LOG_NOTICE, 'Command %s' % '|'.join(cmd))

        return self.module.run_command(cmd, use_unsafe_shell=use_unsafe_shell, data=data)

    def dict_to_string(self, d):
        # Try to trivially translate a dictionary's elements into nice string
        # formatting.
        dstr=""
        for key in d:
            val=d[key]
            str_val=""
            add_string=True
            if type(val)==type(dbus.Array([])):
                for elt in val:
                    if type(elt)==type(dbus.Byte(1)):
                        str_val+="%s " % int(elt)
                    elif type(elt)==type(dbus.String("")):
                        str_val+="%s" % elt
            elif type(val)==type(dbus.Dictionary({})):
                dstr+=self.dict_to_string(val)
                add_string=False
            else:
                str_val=val
            if add_string:
                dstr+="%s: %s\n" % ( key, str_val)
        return dstr

    def create_connection_bridge(self):
        cmd=[self.module.get_bin_path('nmcli', True)]
        # format for creating bridge interface
        cmd.append('con')
        cmd.append('add')
        cmd.append('type')
        cmd.append('bridge')
        cmd.append('con-name')
        if self.cname is not None:
            cmd.append(self.cname)
        elif self.ifname is not None:
            cmd.append(self.ifname)
        # ifname
        cmd.append('ifname')
        if self.ifname is not None:
            cmd.append(self.ifname)
        elif self.cname is not None:
            cmd.append(self.cname)
        #
        if self.ip4 is not None:
            cmd.append('ip4')
            cmd.append(self.ip4)
        if self.gw4 is not None:
            cmd.append('gw4')
            cmd.append(self.gw4)
        if self.ip6 is not None:
            cmd.append('ip6')
            cmd.append(self.ip6)
        if self.gw6 is not None:
            cmd.append('gw6')
            cmd.append(self.gw6)
        if self.enabled is not None:
            cmd.append('autoconnect')
            cmd.append(self.enabled)
        return cmd

    def modify_connection_bridge(self):
        cmd=[self.module.get_bin_path('nmcli', True)]
        # format for modifying bridge interface
        return cmd

    def create_connection(self):
        cmd=[]
        if self.type=='team':
            # cmd=self.create_connection_team()
            if (self.dns4 is not None) or (self.dns6 is not None):
                cmd=self.create_connection_team()
                self.execute_command(cmd)
                cmd=self.modify_connection_team()
                self.execute_command(cmd)
                cmd=self.up_connection()
                return self.execute_command(cmd)
            elif (self.dns4 is None) or (self.dns6 is None):
                cmd=self.create_connection_team()
                return self.execute_command(cmd)
        elif self.type=='team-slave':
            if self.mtu is not None:
                cmd=self.create_connection_team_slave()
                self.execute_command(cmd)
                cmd=self.modify_connection_team_slave()
                self.execute_command(cmd)
                # cmd=self.up_connection()
                return self.execute_command(cmd)
            else:
                cmd=self.create_connection_team_slave()
                return self.execute_command(cmd)
        elif self.type=='bond':
            if (self.mtu is not None) or (self.dns4 is not None) or (self.dns6 is not None):
                cmd=self.create_connection_bond()
                self.execute_command(cmd)
                cmd=self.modify_connection_bond()
                self.execute_command(cmd)
                cmd=self.up_connection()
                return self.execute_command(cmd)
            else:
                cmd=self.create_connection_bond()
                return self.execute_command(cmd)
        elif self.type=='bond-slave':
            cmd=self.create_connection_bond_slave()
        elif self.type=='ethernet':
            if (self.mtu is not None) or (self.dns4 is not None) or (self.dns6 is not None):
                cmd=self.create_connection_ethernet()
                self.execute_command(cmd)
                cmd=self.modify_connection_ethernet()
                self.execute_command(cmd)
                cmd=self.up_connection()
                return self.execute_command(cmd)
            else:
                cmd=self.create_connection_ethernet()
                return self.execute_command(cmd)
        elif self.type=='bridge':
            cmd=self.create_connection_bridge()
        elif self.type=='bridge-slave':
            cmd=self.create_connection_bridge_slave()
        elif self.type=='vlan':
            cmd=self.create_connection_vlan()
        elif self.type=='tun':
            cmd=self.create_connection_tun()
        return self.execute_command(cmd)

    def remove_connection(self):
        # self.down_connection()
        cmd=[self.module.get_bin_path('nmcli', True)]
        cmd.append('con')
        cmd.append('del')
        cmd.append(self.cname)
        return self.execute_command(cmd)

    def modify_connection(self):
        cmd=[]
        if self.type=='team':
            cmd=self.modify_connection_team()
        elif self.type=='team-slave':
            cmd=self.modify_connection_team_slave()
        elif self.type=='bond':
            cmd=self.modify_connection_bond()
        elif self.type=='bond-slave':
            cmd=self.modify_connection_bond_slave()
        elif self.type=='ethernet':
            cmd=self.modify_connection_ethernet()
        elif self.type=='bridge':
            cmd=self.modify_connection_bridge()
        elif self.type=='bridge-slave':
            cmd=self.modify_connection_bridge_slave()
        elif self.type=='vlan':
            cmd=self.modify_connection_vlan()
        elif self.type=='tun':
            cmd=self.modify_connection_tun()
        return self.execute_command(cmd)

    ### Compute Services
    def instance_exists(self):
        if self.instance_name is not None:
            return os.path.exists(self.instance_name)
        return False
    #
    def instance_show(self):
        cmd=[self.module.get_bin_path('qemu-img', True)]
        cmd.append('info')
        if self.instance_name is not None:
            cmd.append(self.instance_name)
        return self.execute_command(cmd)
    #
    def create_instance(self):
        cmd=[self.module.get_bin_path('qemu-img', True)]
        # Create image for instance
        #qemu-img create -f qcow2 -o backing_file=winxp.img test01.img 
        # what is this for?:
        #qemu-img create -b /home/dang/vmimages/base-f24.qcow2 \
        #        -f qcow2 /home/dang/vmimages/f24vm-b.qcow2
        cmd.append('create')
        cmd.append('-f')
        cmd.append(self.image_format)
        if self.image_base is not None:
            cmd.append('-o')
            if self.image_base is not None:
                #join() takes iterable list!
                cmd.append("=".join(('backing_file', self.image_base)))
                #cmd.append(self.image_base)
        if self.instance_name is not None:
            cmd.append(self.instance_name)
        if self.image_size is not None:
            cmd.append(self.image_size)
            pass
        return self.execute_command(cmd)

    def instance_boot(self):
        cmd=[self.module.get_bin_path('qemu-kvm', True)]
        # command to start vm
        #qemu-kvm -hda $DIR/images/Fedora-x86_64-20-300G-20150130-sda-odl.qcow2 \
        #        -cpu core2duo,+vmx -enable-kvm \
        #        -smp cpus=2 \
        #        -m 2048 -vnc :3 \
        #        -device e1000,netdev=snet0,mac=DE:AD:BE:EF:12:10 -netdev tap,id=snet0,script=$DIR/scripts/qemu-ifup-stackbr0.sh \
        # Create all network and ip-routing in host then just connect vm
        # sudo qemu-kvm -hda instances/controller.qcow2 -m 1024 -vnc :3 -cdrom cloud-init/default/default-cidata.iso -device e1000,netdev=br_ql_mgmt -netdev tap,id=br_ql_mgmt,ifname=controller-eth0,script=no,downscript=no
        cmd.append('-daemonize')
        cmd.append('-hda')
        if self.instance_name is not None:
            cmd.append(self.instance_name)
        if self.instance_cpu is not None:
            cmd.append('-cpu')
            cmd.append(self.instance_cpu)
        if self.instance_cpus is not None:
            cmd.append('-smp')
            cmd.append("=".join(('cpus', self.instance_cpus)))
        if self.instance_ram is not None:
            cmd.append('-m')
            cmd.append(self.instance_ram)
        if self.instance_vnc is not None:
            cmd.append('-vnc')
            cmd.append(self.instance_vnc)
        # some default
        cmd.append('-display')
        if self.instance_display is not None:
            cmd.append(self.instance_display)
        else:
            cmd.append('sdl')
        cmd.append('-cdrom')
        if self.instance_cdrom is not None:
            cmd.append(self.instance_cdrom)
        else:
            cmd.append('cloud-init/default/default-cidata.iso')


        return self.execute_command(cmd)
    ###/

    ### Image Services
    def image_exists(self):
        return True

    def create_image(self):
        cmd=[self.module.get_bin_path('qemu-img', True)]
        return self.execute_command(cmd)

    def image_show(self):
        cmd=[self.module.get_bin_path('qemu-img', True)]
        cmd.append('info')
        if self.image_name is not None:
            cmd.append(self.image_name)
        return self.execute_command(cmd)
    ###/

    def show(self):
        # Show details of instance
        # action=show instance_name=name
        print json.dumps({
            "time" : date
        })


def main():
    # Parsing argument file
    module=AnsibleModule(
        argument_spec=dict(
            enabled=dict(required=False, default=None, choices=['yes', 'no'], type='str'),
            action=dict(required=False, default=None, choices=['add', 'mod', 'show', 'list', 'boot', 'up', 'down', 'del', 'image-list', 'image-show', 'image-create', 'instance-create'], type='str'),
            state=dict(required=False, default='present', choices=['present', 'absent'], type='str'),
            # VM argument
            instance_name=dict(required=False, type='str'),
            instance_cpu=dict(required=False, type='str'),
            instance_cpus=dict(required=False, type='str'),
            instance_ram=dict(required=False, type='str'),
            instance_vnc=dict(required=False, type='str'),
            instance_display=dict(required=False, type='str'),
            instance_cdrom=dict(required=False, type='str'),
            image_name=dict(required=False, type='str'),
            image_base=dict(required=False, type='str'),
            image_format=dict(required=False, type='str', default='qcow2'),
            image_size=dict(type='str'),
            #
            cname=dict(required=False, type='str'),
            master=dict(required=False, default=None, type='str'),
            autoconnect=dict(required=False, default=None, choices=['yes', 'no'], type='str'),
            ifname=dict(required=False, default=None, type='str'),
            type=dict(required=False, default=None, choices=['ethernet', 'team', 'team-slave', 'bond', 'bond-slave', 'bridge', 'vlan', 'tun'], type='str'),
            ip4=dict(required=False, default=None, type='str'),
            gw4=dict(required=False, default=None, type='str'),
            dns4=dict(required=False, default=None, type='str'),
            ip6=dict(required=False, default=None, type='str'),
            gw6=dict(required=False, default=None, type='str'),
            dns6=dict(required=False, default=None, type='str'),
            slavetype=dict(required=False, default=None, choices=['team', 'bond', 'bridge'], type='str'),
            # Bond Specific vars
            mode=dict(require=False, default="balance-rr", choices=["balance-rr", "active-backup", "balance-xor", "broadcast", "802.3ad", "balance-tlb", "balance-alb", "tun", "tap"], type='str'),
            # Tun Specific vars
            owner=dict(require=False, default=None, type='str'),
            group=dict(require=False, default=None, type='str'),
            miimon=dict(required=False, default=None, type='str'),
            downdelay=dict(required=False, default=None, type='str'),
            updelay=dict(required=False, default=None, type='str'),
            arp_interval=dict(required=False, default=None, type='str'),
            arp_ip_target=dict(required=False, default=None, type='str'),
            # general usage
            mtu=dict(required=False, default=None, type='str'),
            mac=dict(required=False, default=None, type='str'),
            # bridge specific vars
            stp=dict(required=False, default='yes', choices=['yes', 'no'], type='str'),
            priority=dict(required=False, default="128", type='str'),
            slavepriority=dict(required=False, default="32", type='str'),
            forwarddelay=dict(required=False, default="15", type='str'),
            hellotime=dict(required=False, default="2", type='str'),
            maxage=dict(required=False, default="20", type='str'),
            ageingtime=dict(required=False, default="300", type='str'),
            # vlan specific vars
            vlanid=dict(required=False, default=None, type='str'),
            vlandev=dict(required=False, default=None, type='str'),
            flags=dict(required=False, default=None, type='str'),
            ingress=dict(required=False, default=None, type='str'),
            egress=dict(required=False, default=None, type='str'),
        ),
        supports_check_mode=True
    )

    kvmCmd=KvmCmd(module)

    if kvmCmd.syslogging:
        syslog.openlog('ansible-%s' % os.path.basename(__file__))
        syslog.syslog(syslog.LOG_NOTICE, 'KvmCmd instantiated - platform %s' % kvmCmd.platform)
        if kvmCmd.distribution:
            syslog.syslog(syslog.LOG_NOTICE, 'Nuser instantiated - distribution %s' % kvmCmd.distribution)

    rc=None
    out=''
    err=''
    result={}
    result['instance_name']=kvmCmd.instance_name
    result['state']=kvmCmd.state

    # check for issues
    #if nmcli.cname is None:
    #    nmcli.module.fail_json(msg="You haven't specified a name for the connection")

    ### Image Service

    ## Create image
    if kvmCmd.action == 'image-create':
        if kvmCmd.image_exists():
            result['Exists']='Image do exist so we are modifying them'
            # do modify
        if not kvmCmd.image_exists():
            result['Image']=('Image %s is being added' % (kvmCmd.image_name))
            if module.check_mode:
                module.exit_json(changed=True)
                (rc, out, err)=kvmCmd.create_image()
        if rc!=0:
            module.fail_json(name =('No Image named %s exists' % kvmCmd.cname), msg=err, rc=rc)
    ### /-
    ## Show image
    if kvmCmd.action == 'image-show':
        if kvmCmd.image_exists():
            #result['Image']=('Image %s is being added' % (kvmCmd.image_name))
            (rc, out, err)=kvmCmd.image_show()
        if not kvmCmd.image_exists():
            result['Instance']=('Instance %s not exist' % (kvmCmd.instance_name))
            module.fail_json(name =('No Instance named %s exists' % kvmCmd.instance_name), msg='Instance not exists')
        if rc!=0:
            module.fail_json(name =('No Image named %s exists' % kvmCmd.cname), msg=err, rc=rc)
    ### /-

    ### Compute Service

    ## Create vm instance
    if kvmCmd.action == 'instance-create':
        if kvmCmd.state=='absent':
            if kvmCmd.instance_exists():
                if module.check_mode:
                    module.exit_json(changed=True)
                #(rc, out, err)=nmcli.down_connection()
                #(rc, out, err)=nmcli.remove_connection()
            if rc!=0:
                module.fail_json(name =('No Instance named %s exists' % kvmCmd.instance_name), msg=err, rc=rc)
        # fi
        elif kvmCmd.state=='present':
            if kvmCmd.instance_exists():
                result['Exists']='Instance do exist so we are modifying them'
                # do modify
                if module.check_mode:
                    module.exit_json(changed=True) # exit_json ends program!
                (rc, out, err)=kvmCmd.instance_show()
            #
            if not kvmCmd.instance_exists():
                result['Instance']=('Instance %s, base %s, format %s (default qcow2), Size %s (M) is being added' % (kvmCmd.instance_name, kvmCmd.image_base, kvmCmd.image_format, kvmCmd.image_size))
                if module.check_mode:
                    module.exit_json(changed=True)
                (rc, out, err)=kvmCmd.create_instance()
            if rc is not None and rc!=0:
                module.fail_json(name=kvmCmd.instance_name, msg=err, rc=rc)
    ### /-

    ## Boot vm instance
    if kvmCmd.action == 'boot':
        if kvmCmd.state=='absent':
            if kvmCmd.instance_exists():
                if module.check_mode:
                    module.exit_json(changed=True)
                #(rc, out, err)=nmcli.down_connection()
                #(rc, out, err)=nmcli.remove_connection()
            if rc!=0:
                module.fail_json(name =('No Instance named %s exists' % kvmCmd.instance_name), msg=err, rc=rc)
        # fi
        elif kvmCmd.state=='present':
            if not kvmCmd.instance_exists():
                result['Not Exists']='Instance not exist. Trying to Create instance'
                (rc, out, err)=kvmCmd.create_instance()
                (rc, out, err)=kvmCmd.instance_boot()
                # do modify
            if kvmCmd.instance_exists():
                result['Instance']=('Instance %s, cpu %s, ram %s, vnc %s, cdrom %s is being booted' % (kvmCmd.instance_name, kvmCmd.instance_cpus, kvmCmd.instance_ram, kvmCmd.instance_vnc, kvmCmd.instance_cdrom))
                if module.check_mode:
                    module.exit_json(changed=True)
                (rc, out, err)=kvmCmd.instance_boot()
            if rc is not None and rc!=0:
                module.fail_json(name =('Instance named %s can not boot' % kvmCmd.instance_name), msg=err, rc=rc)
    ## /-

    ## Show details of instance
    if kvmCmd.action == 'show':
        if kvmCmd.instance_exists():
            pass
        if not kvmCmd.instance_exists():
            result['Instance']=('Instance %s not exist' % (kvmCmd.instance_name))
            module.fail_json(name =('No Instance named %s exists' % kvmCmd.instance_name), msg='Instance not exists')
    ## /

    if rc is None:
        result['changed']=False
    else:
        result['changed']=True
    if out:
        result['stdout']=out
    if err:
        result['stderr']=err

    module.exit_json(**result)

# import module snippets
from ansible.module_utils.basic import *

main()
