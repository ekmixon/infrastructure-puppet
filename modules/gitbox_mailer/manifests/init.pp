#/etc/puppet/modules/gitbox_mailer/manifests/init.pp

class gitbox_mailer (
  $service_name   = 'gitbox-mailer',
  $shell          = '/bin/bash',
  $service_ensure = 'running',
  $username       = 'root',
  $group          = 'root',
)
{

  
  require python
  
  if !defined(Python::Pip['asfpy']) {
    python::pip {
      'asfpy' :
        provider => pip3,
        ensure   => present;
    }
  }
  if !defined(Python::Pip['pyyaml']) {
    python::pip {
      'pyyaml' :
        provider => pip3,
        ensure   => present;
    }
  }
  if !defined(Python::Pip['ezt']) {
    python::pip {
      'ezt' :
        provider => pip3,
        ensure   => present;
    }
  }
  if !defined(Python::Pip['pygit']) {
    python::pip {
      'pygit' :
        provider => pip3,
        ensure   => present;
    }
  }

  file {
    '/usr/local/etc/gitbox-mailer':
      ensure => directory,
      mode   => '0755',
      owner  => $username,
      group  => $group;
    '/var/run/gitbox-mailer':
      ensure => directory,
      mode   => '0755',
      owner  => 'www-data',
      group  => 'www-data';
    '/usr/local/etc/gitbox-mailer/gitbox-mailer.py':
      mode   => '0755',
      owner  => $username,
      group  => $group,
      source => 'puppet:///modules/gitbox_mailer/gitbox-mailer.py';
    }
    # Set up systemd on first init
    -> file {
      '/lib/systemd/system/gitbox-mailer.service':
        mode   => '0644',
        owner  => 'root',
        group  => 'root',
        source => "puppet:///modules/gitbox_mailer/gitbox-mailer.${::operatingsystem}";
    }
    -> exec { 'staged-systemd-reload':
      command     => 'systemctl daemon-reload',
      path        => [ '/usr/bin', '/bin', '/usr/sbin' ],
      refreshonly => true,
    }
    -> service { $service_name:
        ensure    => $service_ensure,
        subscribe => [
          File['/usr/local/etc/gitbox-mailer/gitbox-mailer.py']
        ]
    }
}
