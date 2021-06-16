#/etc/puppet/modules/gitbox/manifests/init.pp

class gitbox (

  $custom_fragment_80  = '',
  $custom_fragment_443 = '',
  $packages            = ['gitweb', 'libnet-github-perl',
                          'libnet-ldap-perl', 'swaks',
                          'python-ldap', 'python-twisted',
                          'highlight'],

# override below in eyaml

$pbcsUser = '',
$pbcsPwd  = ''

) {

  package {
    $packages:
      ensure => installed,
  }
  
  exec { "pip_asfpy":
    command => "pip install asfpy",
    unless => "pip list | grep asfpy",
    path => '/bin:/usr/bin',
    require => Package['python-pip']
  }
  exec { "pip_pyyaml":
    command => "pip install pyyaml",
    unless => "pip list | grep pyyaml",
    path => '/bin:/usr/bin',
    require => Package['python-pip']
  }
  exec { "pip_pygithub":
    command => "pip install pygithub",
    unless => "pip list | grep pygithub",
    path => '/bin:/usr/bin',
    require => Package['python-pip']
  }

  file { '/x1':
    ensure => directory,
    owner  => 'root',
    group  => 'www-data',
    mode   => '0755',
  }

  file { '/x1/repos':
    ensure  => directory,
    owner   => 'root',
    group   => 'www-data',
    mode    => '0755',
    require => File['/x1'],
  }

  file { '/x1/gitbox':
    source   => 'puppet:///modules/gitbox',
    recurse  => true,
    owner    => 'root',
    group    => 'www-data',
    checksum => 'md5',
    mode     => '0755';
  }

  file { '/x1/gitbox/hooks/post-receive.d/private.py':
      ensure  => 'present',
      owner   => 'root',
      group   => 'www-data',
      mode    => '0640',
      content => template('gitbox/private.py.erb');
  }

  file {
    '/var/www/.ssh':
      ensure => directory,
      owner  => 'www-data',
      group  => 'www-data',
      mode   => '0750';
    '/var/www/.ssh/config':
      ensure => present,
      source => 'puppet:///modules/gitbox/gitconf/config';
  }

  ## Sync log and broken dir
  file {
    '/x1/gitbox/broken':
      ensure  => directory,
      require => Package[$packages],
      owner   => 'www-data',
      group   => 'www-data',
      mode    => '0755';
    '/x1/gitbox/sync.log':
      ensure => present,
      owner  => 'www-data',
      group  => 'www-data',
      mode   => '0755';
    '/x1/gitbox/db':
      ensure => directory,
      owner  => 'www-data',
      group  => 'www-data',
      mode   => '0750';
    '/x1/gitbox/db/backups':
      ensure => directory,
      owner  => 'www-data',
      group  => 'www-data',
      mode   => '0750';
    '/x1/gitbox/logs':
      ensure => directory,
      owner  => 'www-data',
      group  => 'www-data',
      mode   => '0750';
    '/x1/gitbox/conf/ghprb-whitelist':
      ensure => directory,
      owner  => 'www-data',
      group  => 'www-data',
      mode   => '0750';
  }

  file {
    '/etc/gitweb':
      ensure  => directory,
      require => Package[$packages],
      owner   => 'root',
      group   => 'www-data',
      mode    => '0750';
    '/usr/local/sbin/sendmail':
      ensure => link,
      target => '/usr/sbin/sendmail';
    '/etc/gitconfig':
      ensure => present,
      source => 'puppet:///modules/gitbox/gitconfig';
  }

  ## GitWeb modern CSS
  file {
    '/usr/share/gitweb':
      ensure => directory,
      owner  => 'www-data',
      group  => 'www-data',
      mode   => '0750';
    '/usr/share/gitweb/static':
      ensure => directory,
      owner  => 'www-data',
      group  => 'www-data',
      mode   => '0750';
    '/usr/share/gitweb/static/gitweb.css':
      ensure => present,
      owner  => 'www-data',
      group  => 'www-data',
      mode   => '0750',
      source => 'puppet:///modules/gitbox/gitweb/gitweb.css';
  }

  cron {
    'backup-db':
      user        => 'www-data',
      minute      => '25',
      command     => "cd /x1/gitbox/db && /usr/bin/sqlite3 gitbox.db \".backup backups/gitbox.db.$(date +\\%Y\\%m\\%d\\%H).bak\"",
      environment => "PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin\nSHELL=/bin/sh", # lint:ignore:double_quoted_strings
      require     => File['/x1/gitbox/db'];
    'db-cleanup':
      user        => 'www-data',
      minute      => '45',
      command     => "find /x1/gitbox/db/backups -mtime +2 -delete",
      require     => File['/x1/gitbox/db'];
    'generate-index':
      user        => 'www-data',
      minute      => '*/2',
      command     => 'python3 /x1/gitbox/bin/generate-index.py > /tmp/gi-tmp.html && cp /tmp/gi-tmp.html /x1/gitbox/htdocs/repos.html', # lint:ignore:double_quoted_strings, lint:ignore:140chars
      environment => "PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin\nSHELL=/bin/sh"; # lint:ignore:double_quoted_strings
    'generate-authors-txt':
      user        => 'root',
      minute      => '45',
      command     => 'python3 /x1/gitbox/bin/authors.py',
      environment => "PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin\nSHELL=/bin/sh"; # lint:ignore:double_quoted_strings
  }

  ## Unless declared otherwise the default behaviour is to enable these modules
  apache::mod { 'authnz_ldap': }
  apache::mod { 'ldap': }
  apache::mod { 'rewrite': }

  apache::vhost {
    'gitbox-80':
      priority        => '99',
      vhost_name      => '*',
      servername      => 'gitbox.apache.org',
      port            => '80',
      ssl             => false,
      docroot         => '/x1/gitbox/htdocs',
      manage_docroot  => false,
      serveraliases   => ['git.apache.org'],
      custom_fragment => $custom_fragment_80,
      error_log_file  => 'gitbox_error.log',
      directories     => [
        {
          path           => '/x1/gitbox/htdocs',
          options        => ['Indexes', 'FollowSymLinks', 'MultiViews', 'ExecCGI'],
          allow_override => ['All'],
          addhandlers    => [
            {
              handler    => 'cgi-script',
              extensions => ['.cgi']
            }
          ],
        },
      ],
  }

  apache::vhost {
    'gitbox-ssl':
      priority        => '25',
      vhost_name      => '*',
      servername      => 'gitbox.apache.org',
      port            => '443',
      ssl             => true,
      docroot         => '/x1/gitbox/htdocs',
      manage_docroot  => false,
      ssl_cert        => '/etc/ssl/certs/wildcard.apache.org.crt',
      ssl_chain       => '/etc/ssl/certs/wildcard.apache.org.chain',
      ssl_key         => '/etc/ssl/private/wildcard.apache.org.key',
      serveraliases   => ['git.apache.org'],
      custom_fragment => $custom_fragment_443,
      error_log_file  => 'gitbox-ssl_error.log',
      directories     => [
          {
            path           => '/x1/gitbox/htdocs',
            options        => ['Indexes', 'FollowSymLinks', 'MultiViews', 'ExecCGI'],
            allow_override => ['All'],
            addhandlers    => [
              {
                handler    => 'cgi-script',
                extensions => ['.cgi']
              }
            ],
          },
      ],
  }
}
