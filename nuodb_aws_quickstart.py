#!/usr/bin/python

import nuodbawsquickstart
import json
import os
import sys
import time
import unicodedata
import urllib2

def user_prompt(prompt, valid_choices = [], default = None):
  if default != None:
    prompt = "%s [%s] " % (prompt, str(default))
  val = raw_input(prompt)
  if len(valid_choices) == 0:
    if default == None:
      return val
    else:
      return default
  for choice in valid_choices:
    if val == str(choice):
      return choice
  valid_strings = []
  #Handle integer inputs
  for choice in valid_choices:
    valid_strings.append(str(choice))
  print "Invalid choice. Your choices are: [" + ",".join(valid_strings) + "]"
  return user_prompt(prompt, valid_choices)
  
def choose_from_list(params = [], suggested = None):
  # returns index of the list you gave me
  i = 0
  options = []
  while i < len(params):
    if suggested != None and suggested == i:
      suggest_prompt = "<----- SUGGESTED"
    else:
      suggest_prompt = ""
    #print "%s)  %s %s" % (i+1, params[i], suggest_prompt)
    print '{:2d}) {:25} {}'.format(i+1, params[i], suggest_prompt)
    i += 1
    options.append(i)
  return user_prompt("Choose one:", options) - 1

def choose_multiple_from_list(params = []):
  # returns list of indicies from parameters sent
  tally = []
  while True:
    list_to_send = []
    for idx, param in enumerate(params):
      if idx not in tally:
        list_to_send.append(param)
    if len(list_to_send) == 0:
      return tally
    else:
      list_to_send.append("DONE CHOOSING")
      result = choose_from_list(list_to_send)
      if result == len(list_to_send) - 1:
        return tally
      else:
        choice = list_to_send[result]
        for idx, param in enumerate(params):
          if choice == param:
            tally.append(idx)

def get_instance_type(c):
  # Deny choice for now
  return "m3.xlarge"

  instance_types = []
  for offering in nuodbawsquickstart.Zone("us-east-1").connect(c["aws_access_key"], c["aws_secret"]).get_spot_price_history():
    if offering.instance_type not in instance_types and offering.instance_type[0] in ["m", "t", "r", "c"]:
      instance_types.append(offering.instance_type)
  instance_types = sorted(instance_types)
  suggested = None
  for idx, itype in enumerate(instance_types):
    if itype == "m3.xlarge":
      suggested = idx
  result = choose_from_list(instance_types, suggested)
  return instance_types[result]

  
def get_zone_info(c):
  # Find our how many regions
  r = {}
  zone_count = user_prompt("How many AWS regions? (1-7)? ", range(1,8))
  # open a Boto connection to get metadata
  aws_conn = nuodbawsquickstart.Zone("us-east-1").connect(c["aws_access_key"], c["aws_secret"])
  available_zones = aws_conn.get_all_regions()
  if zone_count == "7":
    for zone in available_zones:
      r[zone] = {}
  else:
    i = 0
    while i < int(zone_count):
      regionlist = []
      for zone_obj in available_zones:
        zone = zone_obj.name
        if zone not in r:
          regionlist.append(zone)
      get = int(choose_from_list(sorted(regionlist)))
      r[sorted(regionlist)[get]] = {}
      i += 1
  # amazon has a ton of amis named the same thing. Choose the latest one. Only reliable way I can find is to scrape their wiki. Cache this.
  page_cache = unicodedata.normalize("NFKD", unicode(urllib2.urlopen("http://aws.amazon.com/amazon-linux-ami/").read(), "utf-8"))
  for region in r:
    # Server count 
    r[region]["servers"] = user_prompt(region + " --- How many servers? (1-20) ", range(1,20))
    zone_obj = nuodbawsquickstart.Zone(region)
    zone_conn = zone_obj.connect(c["aws_access_key"], c["aws_secret"])
    
    # Validate SSH Key
    
    keypairs = zone_conn.get_all_key_pairs()
    key_exists = False
    for keypair in keypairs:
      if c['ssh_key'] == keypair.name:
        key_exists = True
    if not key_exists:
      print "Key %s does not exist in region %s. Please fix this and rerun this script" % (c['ssh_key'], region)
      exit(2)
    
    # Choose AMI
    print
    print region + " --- Determining AMIs (Loading...) "
    amis = zone_obj.amis
    ami_dict = {}
    suggested = None
   
    for ami in amis:
      if ami.architecture == "x86_64" and ami.description != None and len(ami.description) > 0 and "ami-" in ami.id and ami.platform != "windows":
        if ami.owner_alias != None:
          if ami.owner_alias.encode('utf-8') == u"amazon" and ami.id in page_cache:
            ami_dict["  ".join([ami.id.encode('utf-8'), ami.description.encode('utf-8')])] = {"id": ami.id, "location": ami.location}
          elif ami.owner_alias.encode('utf8') != u"amazon": 
            ami_dict["  ".join([ami.id.encode('utf-8'), ami.description.encode('utf-8')])] = {"id": ami.id, "location": ami.location}
    ami_descriptions = sorted(ami_dict.keys()) 
    ami_descriptions.append("NONE OF THE ABOVE")
    chosen_ami = None
    for idx, desc in enumerate(ami_descriptions):
      if "HVM EBS" in desc:
        chosen_ami =  ami_dict[desc]['id']
        suggested = idx
        r[region]["ami"] = chosen_ami
    if chosen_ami == None:
      ami_choice = choose_from_list(ami_descriptions, suggested)
      if ami_choice == len(ami_descriptions) - 1:
        print region + " --- Choose the AMI (Loading...) "
        ami_enter = ""
        while "ami-" not in ami_enter:
          ami_enter = user_prompt("Enter the AMI you want to use (ami-xxxxxxxx): ")
        r[region]["ami"] = ami_enter
      else:
        r[region]["ami"] =  ami_dict[ami_descriptions[ami_choice]]['id']
    
    #What subnets to use?
    print
    print region + " --- Finding subnets... "
    subnets = zone_obj.get_subnets()
    for subnet in subnets:
      if subnets[subnet]['state'] == "available" and subnets[subnet]['defaultForAz'] == "true":
        r[region]['subnets'] = [subnets[subnet]['id']]
        r[region]['vpcs'] = [subnets[subnet]['vpc_id']]
    if len(r[region]['subnets'])== 0:
      print "ERROR: Could not determine default subnet in region %s, therefore cannot proceed. Contact AWS to recreate a default VPC and subnet." % region
      exit()
    
    #What security groups to use?
    r[region]['security_group_ids'] = []
    my_security_group = None
    for group in zone_obj.get_security_groups():
      if group.name == "NuoDB_default_ports":
        my_security_group = group.id
    if my_security_group == None:
      res = user_prompt("I am going to create a security group in region %s. It would open the default NuoDB ports and SSH to all IPs. Is this OK? (y/n)" % region, ["y", "n"], "n")
      if res =="y":
        sg = zone_obj.edit_security_group("NuoDB_default_ports", "These are the default NuoDB ports, open to the world. Autogenerated by nuodb.nuodb_demo_storefront_setup", [{"protocol": "tcp", "from_port": 22, "to_port": 22, "cidr_ip": "0.0.0.0/0"}, {"protocol": "tcp", "from_port": 48004, "to_port": 48020, "cidr_ip": "0.0.0.0/0"}, {"protocol": "tcp", "from_port": 8888, "to_port": 8889, "cidr_ip": "0.0.0.0/0"}, {"protocol": "tcp", "from_port": 8080, "to_port": 8080, "cidr_ip": "0.0.0.0/0"}, {"protocol": "tcp", "from_port": 9001, "to_port": 9001, "cidr_ip": "0.0.0.0/0"}], r[region]['vpcs'][0])
        my_security_group = sg.id
      else:
        print "Cannot continue without a security group. Exiting."
        exit()
    r[region]['security_group_ids'] = [my_security_group]

  return r 

#### Create a cluster

def help():
  print "%s create" % sys.argv[0]
  print "%s terminate" % sys.argv[0]
  
def __main__(action = None):
  config_file = "./config.json"
  params = {
            "cluster_name": { "default" : "NuoDBQuickstart", "prompt" : "What is the name of your cluster?"},
            "aws_access_key": {"default" : "", "prompt" : "What is your AWS access key?"},
            "aws_secret": {"default" : "", "prompt" : "What is your AWS secret?"},
            "domain_name": {"default": "domain", "prompt": "What is the name of your NuoDB domain?"},
            "domain_password": {"default": "bird", "prompt": "What is the admin password of your NuoDB domain?"},
            "ssh_key": {"default": "", "prompt": "Enter your ssh keypair name that exists in all the regions you want to start instances:"},
            "ssh_keyfile": {"default": "/home/USER/.ssh/id_rsa", "prompt": "Enter the location of the private key used for ssh. Please use the absolute path: "},
            "alert_email" : {"default" : "","prompt" : "What email address would you like health alerts sent to?"},
          }
  if action == "create":
    #### Gather all the data we need
    c = {}
    if os.path.exists(config_file):
      with open(config_file) as f:
        static_config = json.loads(f.read())
        f.close()
    else:
      static_config = {}
      
    for key in static_config:
      if key in params:
        params[key]['default'] = static_config[key]
    
    for key in sorted(params.keys()):
      #if len(str(params[key]['default'])) > 30:
      #  default = str(params[key]['default'])[0:27] + "..."
      #else:
      default = str(params[key]['default'])
      val = raw_input("%s [%s] " % (params[key]['prompt'], default))
      if len(val) == 0:
        c[key] = params[key]['default']
      else:
        c[key] = val
        
    #### test for ssh key
    if not os.path.exists(c['ssh_keyfile']):
      print "Cannot find ssh private key %s. Please check and run again." % c['ssh_keyfile']
      exit(2)

    #### Get Instance type
    if "instance_type" not in static_config:
      c['instance_type'] = get_instance_type(c)
    else:
      res = user_prompt("Use the instance type of %s? (y/n) " % static_config['instance_type'], ["y", "n"])
      if res != "y":
        c['instance_type'] = get_instance_type(c)
      else:
        c['instance_type'] = static_config['instance_type']
    
    ### Populate zone data
    if "zones" in static_config:
      print "Found this zone info:"
      for zone in sorted(static_config["zones"].keys()):
        s = static_config["zones"][zone]
        print "{:14}    {:12}    {}    {}    {}".format(zone, s["ami"], str(s["servers"]) + " servers", ",".join(s["subnets"]), ",".join(s["security_group_ids"]))
      res = user_prompt("Use this configuration? (y/n) ", ["y", "n"])
      if res == "y":
        c['zones'] = static_config["zones"]
      else:
        while res != "y":
          c["zones"] = get_zone_info(c)
          for zone in sorted(c["zones"].keys()):
            s = c["zones"][zone]
            print "{:14}    {:12}    {}    {}    {}".format(zone, s["ami"], str(s["servers"]) + " servers", ",".join(s["subnets"]), ",".join(s["security_group_ids"]))
          res = user_prompt("Use this configuration? (y/n) ", ["y", "n"])
    else:
      res = "n"
      while res != "y":
        c["zones"] = get_zone_info(c)
        print "Here is your zone info:"
        for zone in sorted(c["zones"].keys()):
          s = c["zones"][zone]
          print "{:14}    {:12}    {}    {}    {}".format(zone, s["ami"], str(s["servers"]) + " servers", ",".join(s["subnets"]), ",".join(s["security_group_ids"]))
        res = user_prompt("Use this configuration? (y/n) ", ["y", "n"])
      
    # Write out the config
    with open(config_file, 'wt') as f:
      f.write(json.dumps(c, indent=4, sort_keys=True))
    
    #######################################
    #### Actually do some work
    #######################################
    
    mycluster =  nuodbawsquickstart.Cluster(
                                           alert_email = c['alert_email'], ssh_key = c['ssh_key'], ssh_keyfile = c['ssh_keyfile'],
                                           aws_access_key = c['aws_access_key'], aws_secret = c['aws_secret'], 
                                           cluster_name = c['cluster_name'], domain_name = c['domain_name'],
                                           domain_password = c['domain_password'], instance_type = c['instance_type'])
    print "Creating the cluster."
    count = 0
    for zone in c['zones']:
      mycluster.connect_zone(zone)
      z = c['zones'][zone]
      for i in range(0,z['servers']):
        root_name = "%s-%i" % (c['cluster_name'], count)
        myserver = mycluster.add_host(name=root_name, zone=zone, ami=z['ami'], subnets=z['subnets'], security_group_ids = z['security_group_ids']) # Mark the number of nodes to be created
        print "Added %s (%s)" % (root_name, myserver.region)
        count += 1
    
    print "Booting the cluster"
    mycluster.create_cluster() # Actually spins up the nodes.
    hosts = mycluster.get_hosts()
    
    print("Waiting for an available web console")
    healthy = False
    i=0
    wait = 600 #seconds
    good_host = None
    while i < wait:
      if not healthy:
        for host_id in hosts:
          obj = mycluster.get_host(host_id)['host']
          address = mycluster.get_host_address(host_id)
          url = "http://%s:%s" % (address, obj.autoconsole_port)
          if not healthy:
            try:
              urllib2.urlopen(url, None, 2)
              good_host = url
              healthy = True
            except:
              pass
        time.sleep(1)
      i += 1
    if not healthy:
      print "Gave up trying after %s seconds. Check the server" % str(wait)
    else:
      print "You can now access the console at %s " % str(good_host)
      print "Other nodes may still be booting and will join the cluster eventually."
    
  ########################
  #### Terminate a cluster
  ########################
  elif action == "terminate":
    if os.path.exists(config_file):
      with open(config_file) as f:
        c = json.loads(f.read())
        f.close()
      mycluster =  nuodbawsquickstart.Cluster(
                                             alert_email = c['alert_email'], ssh_key = c['ssh_key'], ssh_keyfile = c['ssh_keyfile'],
                                             aws_access_key = c['aws_access_key'], aws_secret = c['aws_secret'], 
                                             cluster_name = c['cluster_name'], domain_name = c['domain_name'],
                                             domain_password = c['domain_password'], instance_type = c['instance_type'])
      for zone in c['zones']:
        mycluster.connect_zone(zone)
      mycluster.terminate_hosts()
    else:
      print "Can't find a previous config file to auto-terminate. If you can't find the file then you will have to destroy the cluster by hand."
      exit(2)
  else:
    help()

args = sys.argv
if len(args) < 2:
  res = user_prompt("What action do you want to take on the cluster? (create/terminate): ", ["create", "terminate"])
  __main__(action=res)
else:
  __main__(action=args[1])