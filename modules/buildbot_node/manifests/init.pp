##/etc/puppet/modules/buildbot_node/manifests/init.pp

class buildbot_node (

  $group_present     = 'present',
  $groupname         = 'buildslave',
  $groups            = [],
  $shell             = '/bin/bash',
  $user_present      = 'present',
  $username          = 'buildslave',
  $service_name      = 'buildslave',
  $gradle_versions   = ['4.6', '4.7', '4.8.1','4.10','4.10.3'],

  # override below in eyaml

  $slave_name,
  $slave_password,
  $gsr_user,
  $gsr_pw,
  $buildbot_svn_credentials,
  $nexus_password = '',
  $npmrc_password = '',
  $bb_basepackages = [],

){

  $slave_dir = "/home/${username}/slave"

  include buildbot_node::buildbot

  # install gradle PPA and gradle 2.x

  apt::ppa { 'ppa:cwchien/gradle':
    ensure => present,
  }
  -> package { 'gradle':
    ensure => latest,
  }

  # define gradle symlinking.
  define buildbot_nodes::symlink_gradle ($versions = $title) {
    package {"gradle-${versions}":
      ensure => latest,
    }
  }

  buildbot_nodes::symlink_gradle { $gradle_versions: }



  python::pip { 'Flask':
    pkgname => 'Flask';
  }

  # merge required packages from hiera for slaves

  $slave_packages = hiera_array('buildbot_node::required_packages',[])

  package {
    $bb_basepackages:
      ensure => 'present',
  }

  # slave specific packages defined in hiera

  -> package {
    $slave_packages:
      ensure => 'present',
  }

  -> class { 'oraclejava::install':
    ensure  => 'latest',
    version => '8',
  }

  # buildbot specific

  -> group {
    $groupname:
      ensure => $group_present,
      system => true,
  }

  -> user {
    $username:
      ensure     => $user_present,
      system     => true,
      name       => $username,
      home       => "/home/${username}",
      shell      => $shell,
      gid        => $groupname,
      groups     => $groups,
      managehome => true,
      require    => Group[$groupname],
  }

  # Bootstrap the buildslave service

  -> exec {
    'bootstrap-buildslave':
      command => "/usr/bin/buildslave create-slave --umask=002 /home/${username}/slave 10.40.0.13:9989 ${slave_name} ${slave_password}",
      creates => "/home/${username}/slave/buildbot.tac",
      user    => $username,
      timeout => 1200,
  }

  -> file {
    "/home/${username}/.git-credentials":
      content => template('buildbot_node/git-credentials.erb'),
      mode    => '0640',
      owner   => $username,
      group   => $groupname;

    "/home/${username}/.gitconfig":
      ensure => 'present',
      source => 'puppet:///modules/buildbot_node/gitconfig',
      mode   => '0644',
      owner  => $username,
      group  => $groupname;

    "/home/${username}/.m2":
      ensure  => directory,
      require => User[$username],
      owner   => $username,
      group   => $groupname,
      mode    => '0755';

    "/home/${username}/.gradle":
      ensure  => directory,
      require => User[$username],
      owner   => $username,
      group   => $groupname,
      mode    => '0755';

    "/home/${username}/.puppet-lint.rc":
      require => User[$username],
      path    => "/home/${username}/.puppet-lint.rc",
      owner   => $username,
      group   => $groupname,
      mode    => '0640',
      source  => 'puppet:///modules/buildbot_node/.puppet-lint.rc';

    "/home/${username}/.m2/settings.xml":
      require => File["/home/${username}/.m2"],
      path    => "/home/${username}/.m2/settings.xml",
      owner   => $username,
      group   => $groupname,
      mode    => '0640',
      content => template('buildbot_node/m2_settings.erb');

    "/home/${username}/.m2/toolchains.xml":
      require => File["/home/${username}/.m2"],
      path    => "/home/${username}/.m2/toolchains.xml",
      owner   => $username,
      group   => $groupname,
      mode    => '0640',
      source  => 'puppet:///modules/buildbot_node/toolchains.xml';

    "/home/${username}/.gradle/gradle.properties":
      require => File["/home/${username}/.gradle"],
      path    => "/home/${username}/.gradle/gradle.properties",
      owner   => $username,
      group   => $groupname,
      mode    => '0640',
      content => template('buildbot_node/gradle_properties.erb');

    "/home/${username}/.ssh":
      ensure  => directory,
      owner   => $username,
      group   => $groupname,
      mode    => '0700',
      require => User[$username];

    "/home/${username}/.ssh/config":
      require => File["/home/${username}/.ssh"],
      path    => "/home/${username}/.ssh/config",
      owner   => $username,
      group   => $groupname,
      mode    => '0640',
      source  => 'puppet:///modules/buildbot_node/ssh/config';

    "/home/${username}/.subversion":
      ensure => directory,
      owner  => $username,
      group  => $groupname,
      mode   => '0750';
    "/home/${username}/.subversion/auth":
      ensure  => directory,
      owner   => $username,
      group   => $groupname,
      mode    => '0750',
      require => File["/home/${username}/.subversion"];
    "/home/${username}/.subversion/auth/svn.simple":
      ensure  => directory,
      owner   => $username,
      group   => $groupname,
      mode    => '0750',
      require => File["/home/${username}/.subversion/auth"];
    "/home/${username}/.subversion/auth/svn.simple/d3c8a345b14f6a1b42251aef8027ab57":
      ensure  => present,
      owner   => $username,
      group   => $groupname,
      mode    => '0640',
      content => template('buildbot_node/svn-credentials.erb'),
      require => File["/home/${buildbot_node::username}/.subversion/auth/svn.simple"];

    "/home/${username}/slave":
      ensure  => directory,
      owner   => $username,
      group   => $groupname,
      require => Exec['bootstrap-buildslave'];

    "/home/${username}/slave/buildbot.tac":
      content => template('buildbot_node/buildbot.tac.erb'),
      mode    => '0644',
      require => Exec['bootstrap-buildslave'];

    "/home/${username}/slave/private.py":
      content => template('buildbot_node/private.py.erb'),
      owner   => $username,
      mode    => '0640',
      require => Exec['bootstrap-buildslave'];

    "/home/${username}/slave/info/host":
      content => template('buildbot_node/host.erb'),
      mode    => '0644',
      require => Exec['bootstrap-buildslave'];

    "/home/${username}/slave/info/admin":
      content => template('buildbot_node/admin.erb'),
      mode    => '0644',
      require => Exec['bootstrap-buildslave'];
  }

  ::systemd::unit_file { 'buildslave.service':
      content => template('buildbot_node/buildslave.service.erb'),
}

}
