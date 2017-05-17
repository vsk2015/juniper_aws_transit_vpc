######################################################################################################################
#  Copyright 2016 Amazon.com, Inc. or its affiliates. All Rights Reserved.                                           #
#                                                                                                                    #
#  Licensed under the Amazon Software License (the "License"). You may not use this file except in compliance        #
#  with the License. A copy of the License is located at                                                             #
#                                                                                                                    #
#      http://aws.amazon.com/asl/                                                                                    #
#                                                                                                                    #   
#  or in the "license" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES #
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions    #
#  and limitations under the License.                                                                                #
######################################################################################################################

import boto3
from botocore.client import Config
from jnpr.junos.device import Device
from jnpr.junos.utils.config import Config as ConfigNet
import paramiko
from xml.dom import minidom
import ast
import traceback
import time
import os
import string
import logging
log = logging.getLogger()
log.setLevel(logging.INFO)
from jinja2 import Environment, FileSystemLoader

config_file = 'transit_vpc_config.txt'
#These S3 endpoint URLs are provided to support VPC endpoints for S3 in regions such as Frankfort that require explicit region endpoint definition
endpoint_url = {
    "us-east-1" : "https://s3.amazonaws.com",
    "us-east-2" : "https://s3-us-east-2.amazonaws.com",
    "us-west-1" : "https://s3-us-west-1.amazonaws.com",
    "us-west-2" : "https://s3-us-west-2.amazonaws.com",
    "eu-west-1" : "https://s3-eu-west-1.amazonaws.com",
    "eu-central-1" : "https://s3-eu-central-1.amazonaws.com",
    "ap-northeast-1" : "https://s3-ap-northeast-1.amazonaws.com",
    "ap-northeast-2" : "https://s3-ap-northeast-2.amazonaws.com",
    "ap-south-1" : "https://s3-ap-south-1.amazonaws.com",
    "ap-southeast-1" : "https://s3-ap-southeast-1.amazonaws.com",
    "ap-southeast-2" : "https://s3-ap-southeast-2.amazonaws.com",
    "sa-east-1" : "https://s3-sa-east-1.amazonaws.com"
}

#Logic to determine when the prompt has been discovered
def prompt(chan):
    buff = ''
    while not (buff.endswith('% ') or buff.endswith('> ') or buff.endswith('# ')):
        resp = chan.recv(9999)
        buff += resp
        #log.info("response: %s",resp)
    return buff

def render_template(vpn_status, context, template_read):
        TEMPLATE_ENVIRONMENT = Environment(autoescape=False,trim_blocks=False,)
        if vpn_status == 'delete':
            return TEMPLATE_ENVIRONMENT.from_string(template_read).render(context)
        else:
            return TEMPLATE_ENVIRONMENT.from_string(template_read).render(context)
                

def netconfEnable(ssh,vsrx_name):
    log.info('Will enable netconf on vSRX')
    ssh.send('cli\n')
    time.sleep(2)
    prompt(ssh)
    ssh.send('configure\n')
    ssh.send('set system services netconf ssh\n')
    ssh.send('set system host-name {}\n'.format(vsrx_name))
    ssh.send('set system root-authentication encrypted-password "$5$SkeASJkC$lB6ycFLL.2MJRZoMXD42kPLM6Dyx0qpht0yxHrStun6"\n')
    ssh.send('commit and-quit\n')
    time.sleep(30)
    log.info("%s", prompt(ssh))

def geIps(ip,net):
    mask=net.split("/")
    ipAddr = ip + "/" + mask[1]
    octet4 = mask[0].split(".")[3]
    gw = int(octet4) + 1
    list1 = mask[0].split(".")
    list1[3]=str(gw)
    gateway = ".".join(list1)
    log.info("IP %s GW %s  ", ipAddr, gateway)
    return ipAddr, gateway
# Logic to figure out the next availble tunnel   
def getNextTunnelId(ssh):
    log.info('Start getNextTunnelId')
    #ssh.send('set cli screen-length 0\n')
    #log.info("%s", prompt(ssh))
    #ssh.send('edit\n')
    #log.info("%s", prompt(ssh))
    # Sysco: 
    #   ssh.send('do show int summary | include Tunnel\n')
    #log.info("%s", prompt(ssh))
    output = ''
    ssh.send('cli\n')
    prompt(ssh)
    ssh.send('show interface terse st0.* | last | match st0 | no-more \n')
    output = prompt(ssh)
    log.info("%s", output)
    #ssh.send('exit\n')
    #log.info("%s", prompt(ssh))

    lastTunnelNum = ''
    for line in output.split('\n'):
        log.info('line: %s',line)
        if line.strip()[:4] == 'st0.':
            #line = line.replace('* st0', 'st0')
            log.info("%s", line)
            lastTunnelNum = line.strip().partition(' ')[0].replace('st0.','')

    ssh.send('exit\n')

    if lastTunnelNum == '':
        return 1
    else:
        return 1 + int(lastTunnelNum)

# Logic to figure out existing tunnel IDs
def getExistingTunnelId(ssh, vpn_connection_id, tvar):
    log.info('Start getExistingTunnelId')
    ssh.send('cli\n')
    prompt(ssh)
    #log.debug("%s", prompt(ssh))
    output = ''

    #FIXME
    cli_command = 'show configuration security ipsec vpn {}-{} | display set | match bind-interface | no-more\n'.format(vpn_connection_id,tvar)
    ssh.send(cli_command)
    #vpn-aws-vpn-
    output = prompt(ssh)
    log.info("Output in delete getExistingTunnelId: %s", output)
    log.debug("%s", output)
    tunnelNum = 0

    #changes - start

    for line in output.split('\n'):
        if 'match bind-interface' not in line:
            for word in line.split(' '):
                if 'st0' in word:
                    tunnelNum = int(word.replace('st0.',''))
            
    if tunnelNum < 0:
        return 0
    else:
        return tunnelNum
"""
#Generic logic to push pre-generated config to the router
def pushConfig(ssh, config):
    #log.info("Starting to push config")
    #ssh.send('term len 0\n')
    #prompt(ssh)
    #CISCO --ssh.send('config t\n')
    log.info("Config received for push %s", config)
    ssh.send('edit\n')
    log.debug("%s", prompt(ssh))
    stime = time.time()
    for line in config[0].split("\n"):
        if line == "WAIT":
            log.debug("Waiting 30 seconds...")
            time.sleep(30)
        else:
            ssh.send(line+'\n')
            log.info("%s", prompt(ssh))
    
    log.info("Saving config!")
    ssh.send('save /var/log/AWS_config.txt\n\n\n\n\n')
    log.info("Saved config!")
    time.sleep(15)
    #log.info("%s", prompt(ssh))
    log.info("Committing---")
    ssh.send('commit\n')
    time.sleep(30)
    ssh.send('exit\n')
    #log.info("%s", prompt(ssh))
    log.debug("   --- %s seconds ---", (time.time() - stime))
    ##ssh.send('copy run start\n\n\n\n\n')
    ssh.send('exit\n')
    #log.info("%s", prompt(ssh))
    log.info("Update complete!")"""

def pushConfig(vsrx_ip, configjuniper,config):
    dev = Device(vsrx_ip,user=config['USER_NAME'],ssh_private_key_file="/tmp/"+config['PRIVATE_KEY']) 
    log.info("Generated config\n %s \n %s ", configjuniper[0],configjuniper[1]) 
    dev.open()
    dev.bind(cfg=ConfigNet)
    log.info("Locking candidate config")
    if dev.cfg.lock():
        log.info("Candidate config lock. Successful.")
    for conf in configjuniper: 
        dev.cfg.load(conf,format="set",ignore_warning='statement not found') 
        #rollback if above fails to be added by me
    log.info("Below changes made by user %s will be commited---", config['USER_NAME'] )
    dev.cfg.pdiff()
    try:
        log.info("Committing---")
        dev.cfg.commit()
    except:
        dev.cfg.rollback(0)
        log.info("Rollback performed!!")
        dev.cfg.unlock()
        dev.close()
        s=traceback.format_exc()
        raise
    log.info("Unlocking candidate config")
    dev.cfg.unlock()
    dev.close()

#Logic to determine the bucket prefix from the S3 key name that was provided
def getBucketPrefix(bucket_name, bucket_key):
    #Figure out prefix from known bucket_name and bucket_key
    bucket_prefix = '/'.join(bucket_key.split('/')[:-2])
    if len(bucket_prefix) > 0:
        bucket_prefix += '/'
    return bucket_prefix

#Logic to download the transit VPC configuration file from S3
def getTransitConfig(bucket_name, bucket_prefix, s3_url, config_file):
    s3 = boto3.client('s3', endpoint_url=s3_url,
                      config=Config(s3={'addressing_style': 'virtual'}, signature_version='s3v4'))
    log.info("Downloading config file: %s/%s/%s%s", s3_url, bucket_name, bucket_prefix,config_file)
    return ast.literal_eval(s3.get_object(Bucket=bucket_name,Key=bucket_prefix+config_file)['Body'].read())

#Logic to upload a new/updated transit VPC configuration file to S3 (not currently used)
def putTransitConfig(bucket_name, bucket_prefix, s3_url, config_file, config):
    s3=boto3.client('s3', endpoint_url=s3_url,
                    config=Config(s3={'addressing_style': 'virtual'}, signature_version='s3v4'))
    log.info("Uploading new config file: %s/%s/%s%s", s3_url,bucket_name, bucket_prefix,config_file)
    log.info("config data received %s" ,config)
    w=s3.put_object(
              Body=str.encode(config.__str__()),
              Bucket=bucket_name,
              Key=bucket_prefix+config_file,
              ACL='bucket-owner-full-control',
              ServerSideEncryption='aws:kms',
              SSEKMSKeyId=config['KMS_KEY']
              )
#Logic to download the SSH private key from S3 to be used for SSH public key authentication
def downloadPrivateKey(bucket_name, bucket_prefix, s3_url, prikey):
    if os.path.exists('/tmp/'+prikey):
        os.remove('/tmp/'+prikey)
    s3=boto3.client('s3', endpoint_url=s3_url,
                    config=Config(s3={'addressing_style': 'virtual'}, signature_version='s3v4'))
    log.info("Downloading private key: %s/%s/%s%s",s3_url, bucket_name, bucket_prefix, prikey)
    s3.download_file(bucket_name,bucket_prefix+prikey, '/tmp/'+prikey)


#Logic to create the appropriate Sysco configuration
def create_jnpr_config(bucket_name, bucket_key, s3_url,config, vsrx, ssh):
    log.info("Processing %s/%s", bucket_name, bucket_key)
    template_bucket_name=config['TEMPLATE_BUCKET_NAME']
    bgp_asn=config['BGP_ASN']
    if vsrx == 'VSRX1':
        ipPri=config['PIPGEINT1']
        netPub = config['PUBSUBNET12']
    elif vsrx == 'VSRX2':
        ipPri=config['PIPGEINT2']
        netPub = config['PUBSUBNET22']
    geIp, routeGw = geIps(ipPri,netPub)
    #Download the VPN configuration XML document
    s3=boto3.client('s3',endpoint_url=s3_url,
                    config=Config(s3={'addressing_style': 'virtual'}, signature_version='s3v4'))
    log.info("s3 %s", s3)
    config=s3.get_object(Bucket=bucket_name,Key=bucket_key)
    log.info("Config %s", config)
    xmldoc=minidom.parseString(config['Body'].read())
    log.info("xmldoc %s", xmldoc)
    #Extract transit_vpc_configuration values
    vpn_config = xmldoc.getElementsByTagName("transit_vpc_config")[0]
    log.info("vpn_config %s", vpn_config)
    account_id = vpn_config.getElementsByTagName("account_id")[0].firstChild.data
    log.info("account_id %s", account_id)
    vpn_endpoint = vpn_config.getElementsByTagName("vpn_endpoint")[0].firstChild.data
    log.info("vpn_endpoint %s", vpn_endpoint)
    vpn_status = vpn_config.getElementsByTagName("status")[0].firstChild.data
    log.info("vpn_status %s", vpn_status)
    preferred_path = vpn_config.getElementsByTagName("preferred_path")[0].firstChild.data
    log.info("preferred_path %s", preferred_path)

    #Extract VPN connection information
    vpn_connection=xmldoc.getElementsByTagName('vpn_connection')[0]
    log.info("vpn_connection %s", vpn_connection)
    vpn_connection_id=vpn_connection.attributes['id'].value
    log.info("vpn_connection_id %s", vpn_connection_id)
    customer_gateway_id=vpn_connection.getElementsByTagName("customer_gateway_id")[0].firstChild.data
    log.info("customer_gateway_id %s", customer_gateway_id)
    vpn_gateway_id=vpn_connection.getElementsByTagName("vpn_gateway_id")[0].firstChild.data
    log.info("vpn_gateway_id %s", vpn_gateway_id)
    vpn_connection_type=vpn_connection.getElementsByTagName("vpn_connection_type")[0].firstChild.data
    log.info("vpn_connection_type %s", vpn_connection_type)

    tunnelId=0
    #Determine the VPN tunnels to work with
    if vpn_status == 'create':    
        tunnelId=getNextTunnelId(ssh)
    '''
    else:
        tunnelId=getExistingTunnelId(ssh,vpn_connection_id)
        if tunnelId == 0:
            return
    '''

    log.info("%s %s with tunnel #%s and #%s.",vpn_status, vpn_connection_id, tunnelId, tunnelId+1)
    # Create or delete the VRF for this connection
    if vpn_status == 'delete':
        config_text=[]
        #config_text.append('cli \n')
        #config_text.append('configure \n')

        ipsec_tunnel_var = 0
        for ipsec_tunnel in vpn_connection.getElementsByTagName("ipsec_tunnel"):
            ipsec_tunnel_var += 1
            tunnelId=getExistingTunnelId(ssh,vpn_connection_id,ipsec_tunnel_var)
            if tunnelId == 0:
                return
            s3=boto3.client('s3',endpoint_url="https://s3.amazonaws.com",config=Config(s3={'addressing_style': 'virtual'}, signature_version='s3v4',region_name="us-east-1"))
            template_read=s3.get_object(Bucket=template_bucket_name,Key="delete/vsrx_delete.txt")['Body'].read()
            context = {'vpn_connection_id': vpn_connection_id,'ipsec_tunnel_var' : ipsec_tunnel_var,'tunnelId' : tunnelId}
            config_vpn_delete=render_template(vpn_status, context, template_read)
            #log.info("Rendered config for delete %s", config_vpn_delete )
            config_text.append(config_vpn_delete)   
      #------Juniper Delete-----#
    else:
        config_text=[]
        #config_text.append('cli \n')
        #config_text.append('configure \n')

        ipsec_tunnel_var = 0
          # Create tunnel specific configuration
        for ipsec_tunnel in vpn_connection.getElementsByTagName("ipsec_tunnel"):
            ipsec_tunnel_var += 1
            customer_gateway=ipsec_tunnel.getElementsByTagName("customer_gateway")[0]
            log.info("customer_gateway %s", customer_gateway)
            customer_gateway_tunnel_outside_address=customer_gateway.getElementsByTagName("tunnel_outside_address")[0].getElementsByTagName("ip_address")[0].firstChild.data
            log.info("customer_gateway_tunnel_outside_address %s", customer_gateway_tunnel_outside_address)
            customer_gateway_tunnel_inside_address_ip_address=customer_gateway.getElementsByTagName("tunnel_inside_address")[0].getElementsByTagName("ip_address")[0].firstChild.data
            log.info("customer_gateway_tunnel_inside_address_ip_address %s", customer_gateway_tunnel_inside_address_ip_address)
            customer_gateway_tunnel_inside_address_network_mask=customer_gateway.getElementsByTagName("tunnel_inside_address")[0].getElementsByTagName("network_mask")[0].firstChild.data
            log.info("customer_gateway_tunnel_inside_address_network_mask %s", customer_gateway_tunnel_inside_address_network_mask)
            customer_gateway_tunnel_inside_address_network_cidr=customer_gateway.getElementsByTagName("tunnel_inside_address")[0].getElementsByTagName("network_cidr")[0].firstChild.data
            log.info("customer_gateway_tunnel_inside_address_network_cidr %s", customer_gateway_tunnel_inside_address_network_cidr)
            customer_gateway_bgp_asn=customer_gateway.getElementsByTagName("bgp")[0].getElementsByTagName("asn")[0].firstChild.data
            log.info("customer_gateway_bgp_asn %s", customer_gateway_bgp_asn)
            customer_gateway_bgp_hold_time=customer_gateway.getElementsByTagName("bgp")[0].getElementsByTagName("hold_time")[0].firstChild.data
            log.info("customer_gateway_bgp_hold_time %s", customer_gateway_bgp_hold_time)

            vpn_gateway=ipsec_tunnel.getElementsByTagName("vpn_gateway")[0]
            log.info("vpn_gateway %s", vpn_gateway)
            vpn_gateway_tunnel_outside_address=vpn_gateway.getElementsByTagName("tunnel_outside_address")[0].getElementsByTagName("ip_address")[0].firstChild.data
            log.info("vpn_gateway_tunnel_outside_address %s", vpn_gateway_tunnel_outside_address)
            vpn_gateway_tunnel_inside_address_ip_address=vpn_gateway.getElementsByTagName("tunnel_inside_address")[0].getElementsByTagName("ip_address")[0].firstChild.data
            log.info("vpn_gateway_tunnel_inside_address_ip_address %s", vpn_gateway_tunnel_inside_address_ip_address)
            vpn_gateway_tunnel_inside_address_network_mask=vpn_gateway.getElementsByTagName("tunnel_inside_address")[0].getElementsByTagName("network_mask")[0].firstChild.data
            log.info("vpn_gateway_tunnel_inside_address_network_mask %s", vpn_gateway_tunnel_inside_address_network_mask)
            vpn_gateway_tunnel_inside_address_network_cidr=vpn_gateway.getElementsByTagName("tunnel_inside_address")[0].getElementsByTagName("network_cidr")[0].firstChild.data
            log.info("vpn_gateway_tunnel_inside_address_network_cidr %s", vpn_gateway_tunnel_inside_address_network_cidr)
            vpn_gateway_bgp_asn=vpn_gateway.getElementsByTagName("bgp")[0].getElementsByTagName("asn")[0].firstChild.data
            log.info("vpn_gateway_bgp_asn %s", vpn_gateway_bgp_asn)
            vpn_gateway_bgp_hold_time=vpn_gateway.getElementsByTagName("bgp")[0].getElementsByTagName("hold_time")[0].firstChild.data
            log.info("vpn_gateway_bgp_hold_time %s", vpn_gateway_bgp_hold_time)

            ike=ipsec_tunnel.getElementsByTagName("ike")[0]
            log.info("ike %s", ike)
            ike_authentication_protocol=ike.getElementsByTagName("authentication_protocol")[0].firstChild.data
            log.info("ike_authentication_protocol %s", ike_authentication_protocol)
            ike_encryption_protocol=ike.getElementsByTagName("encryption_protocol")[0].firstChild.data
            log.info("ike_encryption_protocol %s", ike_encryption_protocol)
            ike_lifetime=ike.getElementsByTagName("lifetime")[0].firstChild.data
            log.info("ike_lifetime %s", ike_lifetime)
            ike_perfect_forward_secrecy=ike.getElementsByTagName("perfect_forward_secrecy")[0].firstChild.data
            log.info("ike_perfect_forward_secrecy %s", ike_perfect_forward_secrecy)
            ike_mode=ike.getElementsByTagName("mode")[0].firstChild.data
            log.info("ike_mode %s", ike_mode)
            ike_pre_shared_key=ike.getElementsByTagName("pre_shared_key")[0].firstChild.data
            log.info("ike_pre_shared_key %s", ike_pre_shared_key)
            
            ipsec=ipsec_tunnel.getElementsByTagName("ipsec")[0]
            log.info("ipsec %s", ipsec)
            ipsec_protocol=ipsec.getElementsByTagName("protocol")[0].firstChild.data
            log.info("ipsec_protocol %s", ipsec_protocol)
            ipsec_authentication_protocol=ipsec.getElementsByTagName("authentication_protocol")[0].firstChild.data
            log.info("ipsec_authentication_protocol %s", ipsec_authentication_protocol)
            ipsec_encryption_protocol=ipsec.getElementsByTagName("encryption_protocol")[0].firstChild.data
            log.info("ipsec_encryption_protocol %s", ipsec_encryption_protocol)
            ipsec_lifetime=ipsec.getElementsByTagName("lifetime")[0].firstChild.data
            log.info("ipsec_lifetime %s", ipsec_lifetime)
            ipsec_perfect_forward_secrecy=ipsec.getElementsByTagName("perfect_forward_secrecy")[0].firstChild.data
            log.info("ipsec_perfect_forward_secrecy %s", ipsec_perfect_forward_secrecy)
            ipsec_mode=ipsec.getElementsByTagName("mode")[0].firstChild.data
            log.info("ipsec_mode %s", ipsec_mode)
            ipsec_clear_df_bit=ipsec.getElementsByTagName("clear_df_bit")[0].firstChild.data
            log.info("ipsec_clear_df_bit %s", ipsec_clear_df_bit)
            ipsec_fragmentation_before_encryption=ipsec.getElementsByTagName("fragmentation_before_encryption")[0].firstChild.data
            log.info("ipsec_fragmentation_before_encryption %s", ipsec_fragmentation_before_encryption)
            ipsec_tcp_mss_adjustment=ipsec.getElementsByTagName("tcp_mss_adjustment")[0].firstChild.data
            log.info("ipsec_tcp_mss_adjustment %s", ipsec_tcp_mss_adjustment)
            ipsec_dead_peer_detection_interval=ipsec.getElementsByTagName("dead_peer_detection")[0].getElementsByTagName("interval")[0].firstChild.data
            log.info("ipsec_dead_peer_detection_interval %s", ipsec_dead_peer_detection_interval)
            ipsec_dead_peer_detection_retries=ipsec.getElementsByTagName("dead_peer_detection")[0].getElementsByTagName("retries")[0].firstChild.data
            log.info("ipsec_dead_peer_detection_retries %s", ipsec_dead_peer_detection_retries)
            
            s3=boto3.client('s3',endpoint_url="https://s3.amazonaws.com",config=Config(s3={'addressing_style': 'virtual'}, signature_version='s3v4',region_name="us-east-1"))
            template_read=s3.get_object(Bucket=template_bucket_name,Key="create/vsrx_create.txt")['Body'].read()
            context= {
                'vpn_connection_id': vpn_connection_id,
                'ipsec_tunnel_var' : ipsec_tunnel_var,
                'ike_pre_shared_key' : ike_pre_shared_key,
                'vpn_gateway_tunnel_outside_address' : vpn_gateway_tunnel_outside_address,
                'tunnelId' : tunnelId,
                'vpn_gateway_tunnel_inside_address_ip_address' : vpn_gateway_tunnel_inside_address_ip_address,
                'vpn_gateway_bgp_asn' : vpn_gateway_bgp_asn,
                'customer_gateway_bgp_asn' : customer_gateway_bgp_asn,
                'customer_gateway_tunnel_inside_address_ip_address' : customer_gateway_tunnel_inside_address_ip_address,
                'vpn_gateway_tunnel_inside_address_network_cidr' : vpn_gateway_tunnel_inside_address_network_cidr,
                'ge_Ip' : geIp,
                'route_Gw' : routeGw
                              }

            config_vpn_create = render_template(vpn_status, context, template_read)
            #log.info("Rendered config for create %s", config_vpn_create )
            config_text.append(config_vpn_create) 
            tunnelId+=1
        
    log.debug("Conversion complete")
    #config_text = []
    return config_text

def lambda_handler(event, context):
    log.info("event data received %s ", event)
    record=event['Records'][0]
    bucket_name=record['s3']['bucket']['name']
    bucket_key=record['s3']['object']['key']
    bucket_region=record['awsRegion']
    bucket_prefix=getBucketPrefix(bucket_name, bucket_key)
    log.debug("Getting config")
    stime = time.time()
    config = getTransitConfig(bucket_name, bucket_prefix, endpoint_url[bucket_region], config_file)
    if 'VSRX1' in bucket_key:
        vsrx_ip=config['PIP1']
        vsrx_name='VSRX1'
    else:
        vsrx_ip=config['PIP2']
        vsrx_name='VSRX2'
    log.info("--- %s seconds ---", (time.time() - stime))
    #Download private key file from secure S3 bucket
    downloadPrivateKey(bucket_name, bucket_prefix, endpoint_url[bucket_region], config['PRIVATE_KEY'])
    log.debug("Reading downloaded private key into memory.")
    k = paramiko.RSAKey.from_private_key_file("/tmp/"+config['PRIVATE_KEY'])
    #Delete the temp copy of the private key
    log.debug("Deleted downloaded private key.")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    log.info("Connecting to %s (%s)", vsrx_name, vsrx_ip)
    stime = time.time()
    try:
        c.connect( hostname = vsrx_ip, username = config['USER_NAME'], pkey = k )
        PubKeyAuth=True
    except paramiko.ssh_exception.AuthenticationException:
        log.error("PubKey Authentication Failed! Connecting with password")
        c.connect( hostname = vsrx_ip, username = config['USER_NAME'], password = config['PASSWORD'] )
        PubKeyAuth=False
    log.info("--- %s seconds ---", (time.time() - stime))
    log.info("Connected to %s",vsrx_ip)
    ssh = c.invoke_shell()
    log.info("%s",prompt(ssh))
    if vsrx_name =='VSRX1' and config['NETCONF1'] == 'DISABLED':
        netconfEnable(ssh,vsrx_name)
        config['NETCONF1'] = 'ENABLED'
        putTransitConfig(bucket_name, bucket_prefix, endpoint_url[bucket_region], config_file, config)
    elif vsrx_name =='VSRX2' and config['NETCONF2'] == 'DISABLED':
        netconfEnable(ssh,vsrx_name)
        config['NETCONF2'] = 'ENABLED'
        putTransitConfig(bucket_name, bucket_prefix, endpoint_url[bucket_region], config_file, config)        
    log.info("Creating config.")
    log.info("bucket_name: %s", bucket_name)
    log.info("bucket_key: %s", bucket_key)
    log.info("endpoint_url[bucket_region]: %s", endpoint_url[bucket_region])
    log.info("config['BGP_ASN']: %s", config['BGP_ASN'])
    stime = time.time()
    vsrx_config = create_jnpr_config(bucket_name, bucket_key, endpoint_url[bucket_region], config,vsrx_name, ssh)
    log.info("--- %s seconds ---", (time.time() - stime))
    log.info("Pushing config to router.")
    stime = time.time()
    pushConfig(vsrx_ip,vsrx_config,config)
    os.remove("/tmp/"+config['PRIVATE_KEY'])
    log.info("--- %s seconds ---", (time.time() - stime))
    ssh.close()

    return
    {
        'message' : "Script execution completed. See Cloudwatch logs for complete output"
    }
