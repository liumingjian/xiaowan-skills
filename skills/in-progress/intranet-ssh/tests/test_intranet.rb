# frozen_string_literal: true

require 'minitest/autorun'
require 'tmpdir'
require 'fileutils'
require 'open3'
require 'rbconfig'
load File.expand_path('../scripts/intranet', __dir__)

class IntranetTest < Minitest::Test
  SOURCE = File.expand_path('../scripts/intranet', __dir__)
  RUBY = '/usr/bin/ruby'

  def setup
    @home = Dir.mktmpdir('intranet home % ')
    @directory = File.join(@home, '.config', 'company-intranet')
    FileUtils.mkdir_p(@directory, mode: 0700)
    @values = { 'server' => '127.0.0.1', 'port' => 1, 'username' => 'proxy-user',
                'password' => 'invented-proxy-password', 'ssh_username' => 'root',
                'ssh_password' => 'invented-ssh-password' }
    save_config
  end

  def teardown
    FileUtils.remove_entry(@home)
  end

  def save_config
    File.write(File.join(@directory, 'config.json'), JSON.generate(@values), mode: 'w', perm: 0600)
  end

  def invoke(*args)
    Open3.capture3({ 'HOME' => @home }, RUBY, SOURCE, *args)
  end

  def test_only_one_canonical_company_ip_is_accepted
    [[], ['up'], ['down'], ['status'], ['test'], ['configure'], ['10.0.0.1'],
     ['192.168.01.1'], ['192.168.1.256'], ['192.168.1.1', 'id'],
     ['192.168.1.1;id'], ['--internal-proxy'], ['--internal-proxy', '10.0.0.1']].each do |args|
      _out, err, status = invoke(*args)
      refute status.success?, args.inspect
      assert_match(/Expected one IPv4|Usage:/, err)
      refute_includes err, 'invented'
    end
    %w[-h --help].each do |flag|
      out, err, status = invoke(flag)
      assert status.success?
      assert_match(/Usage: intranet/, out)
      assert_empty err
    end
  end

  def test_private_configuration_and_password_constraints
    config = File.join(@directory, 'config.json')
    File.chmod(0644, config)
    assert_match(/permissions/, invoke('192.168.1.116')[1])
    File.chmod(0600, config)
    File.chmod(0755, @directory)
    assert_match(/permissions/, invoke('192.168.1.116')[1])
    File.chmod(0700, @directory)
    ["line\nbreak", "nul\0byte", 'x' * 1025, ''].each do |password|
      @values['ssh_password'] = password
      save_config
      _out, err, status = invoke('192.168.1.116')
      refute status.success?
      assert_match(/invalid proxy or SSH credentials/, err)
      refute_includes err, password unless password.empty?
    end
    @values['ssh_password'] = 'invented'
    @values['password'] = 'x' * 256
    save_config
    assert_match(/invalid proxy or SSH credentials/, invoke('192.168.1.116')[1])
    File.rename(config, config + '.real')
    File.symlink(config + '.real', config)
    assert_match(/Cannot read/, invoke('192.168.1.116')[1])
  end

  def test_exec_uses_fd3_and_fixed_native_ssh_arguments_without_secret_environment
    probe = File.join(@home, 'fake sshpass')
    File.write(probe, "#!/usr/bin/ruby\nrequire 'json'\npassword = IO.for_fd(3).read\nputs JSON.generate('argv' => ARGV, 'password' => password, 'environment' => ENV.to_h)\nexit 23\n", mode: 'w', perm: 0700)
    runner = "load ARGV.shift; module Intranet; def self.sshpass_path; ENV.fetch('INTRANET_TEST_PROBE'); end; end; exit Intranet.run(ARGV)"
    out, err, status = Open3.capture3({ 'HOME' => @home, 'INTRANET_TEST_PROBE' => probe }, RUBY, '-e', runner, SOURCE, '192.168.1.116')
    assert_equal 23, status.exitstatus
    assert_empty err
    result = JSON.parse(out)
    assert_equal "invented-ssh-password\n", result['password']
    args = result['argv']
    assert_equal ['-d', '3', '/usr/bin/ssh', '-F', '/dev/null', '-tt', '-l', 'root', '-p', '22'], args[0, 10]
    assert_equal '192.168.1.116', args.last
    %w[StrictHostKeyChecking=accept-new GlobalKnownHostsFile=/dev/null UpdateHostKeys=no PreferredAuthentications=password PubkeyAuthentication=no KbdInteractiveAuthentication=no NumberOfPasswordPrompts=1 ConnectTimeout=15].each { |setting| assert_includes args, setting }
    assert args.any? { |arg| arg.start_with?('ProxyCommand=') && arg.include?('--internal-proxy') }
    refute_match(/invented/, args.join(' '))
    refute_match(/invented/, JSON.generate(result['environment']))
    hosts = File.join(@directory, 'known_hosts')
    assert_equal 0600, File.stat(hosts).mode & 0777
    options = args.drop(3)
    native_out, native_err, native_status = Open3.capture3('/usr/bin/ssh', '-G', *options)
    assert native_status.success?, native_err
    assert_includes native_out, "userknownhostsfile #{hosts}\n"
  end

  def probe_invocation(body, *args)
    probe = File.join(@home, 'fake sshpass')
    File.write(probe, <<~RUBY, mode: 'w', perm: 0700)
      #!/usr/bin/ruby
      require 'json'
      password = IO.for_fd(3).read
      File.write(ENV.fetch('INTRANET_TEST_RESULT'), JSON.generate('argv' => ARGV, 'password' => password, 'environment' => ENV.to_h))
      #{body}
    RUBY
    runner = "load ARGV.shift; module Intranet; def self.sshpass_path; ENV.fetch('INTRANET_TEST_PROBE'); end; end; exit Intranet.run(ARGV)"
    [{ 'HOME' => @home, 'INTRANET_TEST_PROBE' => probe, 'INTRANET_TEST_RESULT' => File.join(@home, 'probe-result.json') }, RUBY, '-e', runner, SOURCE, *args]
  end

  def probe_result
    result = JSON.parse(File.read(File.join(@home, 'probe-result.json')))
    assert_equal "invented-ssh-password\n", result['password']
    refute_match(/invented/, result['argv'].join(' '))
    refute_match(/invented/, JSON.generate(result['environment']))
    result['argv']
  end

  def test_exec_streams_live_binary_stdin_stdout_stderr_and_preserves_remote_status
    body = <<~'RUBY'
      STDIN.binmode
      STDOUT.binmode
      STDERR.binmode
      STDOUT.sync = true
      STDOUT.write(STDIN.read(3))
      STDOUT.write(STDIN.read)
      STDERR.write("remote error\x00\xff".b)
      exit 37
    RUBY
    command = "printf '%s' '$HOME `uname` \"quoted\"';\ncat"
    first = "\x00\xffA".b
    rest = (0..255).to_a.pack('C*') * 1024
    Open3.popen3(*probe_invocation(body, 'exec', '192.168.1.116', command)) do |input, output, error, wait|
      [input, output, error].each(&:binmode)
      input.write(first)
      input.flush
      assert_equal first, Timeout.timeout(3) { output.read(3) }
      refute input.closed?
      input.write(rest)
      input.close
      assert_equal rest, output.read
      assert_equal "remote error\x00\xff".b, error.read
      assert_equal 37, wait.value.exitstatus
    end
    args = probe_result
    assert_equal ['-d', '3', '/usr/bin/ssh', '-F', '/dev/null', '-T', '-l', 'root', '-p', '22'], args[0, 10]
    assert_equal ['192.168.1.116', command], args.last(2)
    refute_includes args, '-tt'
  end

  def test_scp_uses_shared_options_and_literal_file_operands_without_secret_environment
    remote = "/tmp/space 'quote\" $dollar `tick` \\ [*?].bin"
    local = "-local:space 'quote\" $dollar `tick` \\ [*?].bin"
    [
      ['upload', local, remote, [File.expand_path(local), "root@192.168.1.116:#{remote}"]],
      ['download', remote, local, ["root@192.168.1.116:/tmp/space 'quote\" $dollar `tick` \\\\ \\[\\*\\?\\].bin", File.expand_path(local)]]
    ].each do |mode, source, destination, operands|
      out, err, status = Open3.capture3(*probe_invocation('exit 29', mode, '192.168.1.116', source, destination))
      assert_empty out
      assert_empty err
      assert_equal 29, status.exitstatus
      args = probe_result
      assert_equal ['-d', '3', '/usr/bin/scp', '-F', '/dev/null', '-P', '22'], args[0, 7]
      assert_equal ['--', *operands], args.last(3)
      refute_includes args, '-O'
      refute_includes args, '-r'
      assert_equal Intranet.connection_options('192.168.1.116', File.join(@directory, 'known_hosts')), args[7...-3]
    end
  end

  def test_all_operation_options_are_accepted_by_native_ssh
    ip = '192.168.1.116'
    hosts = File.join(@directory, 'known hosts % " \\')
    [[ip], ['exec', ip, 'cat'], ['upload', ip, '-local:name', '/tmp/destination'], ['download', ip, '/tmp/source', '-local:name']].each do |argv|
      args = Intranet.native_argv(Intranet.parse(argv), hosts)
      options = args.each_cons(2).select { |pair| pair.first == '-o' }.flatten
      out, err, status = Open3.capture3('/usr/bin/ssh', '-G', '-F', '/dev/null', '-l', 'root', '-p', '22', *options, ip)
      assert status.success?, err
      assert_includes out, "userknownhostsfile #{hosts}\n"
      assert_includes out, "stricthostkeychecking accept-new\n"
      assert_includes out, "port 22\n"
      assert_includes out, "user root\n"
    end
  end

  def test_invalid_operation_boundaries_are_rejected_before_configuration
    ip = '192.168.1.116'
    invalid = [[], ['exec', ip], ['exec', ip, 'one', 'two'], ['exec', ip, ''], ['exec', ip, "bad\0command"],
               ['upload', ip, '/tmp/local'], ['download', ip, '/tmp/remote'],
               ['upload', ip, 'local', 'relative'], ['download', ip, 'relative', 'local'],
               ['upload', ip, '', '/tmp/remote'], ['download', ip, '/tmp/remote', '']]
    %w[exec upload download].each do |mode|
      args = mode == 'exec' ? ['cat'] : ['/tmp/source', '/tmp/destination']
      invalid << [mode, '10.0.0.1', *args]
      invalid << [mode, '192.168.01.1', *args]
    end
    ["\0", "\n", "\r", "\t", "\x1f", "\x7f"].each do |control|
      invalid << ['upload', ip, "local#{control}", '/tmp/remote']
      invalid << ['upload', ip, 'local', "/tmp/remote#{control}"]
      invalid << ['download', ip, "/tmp/remote#{control}", 'local']
      invalid << ['download', ip, '/tmp/remote', "local#{control}"]
    end
    runner = "load ARGV.shift; module Intranet; def self.config; raise 'configuration reached'; end; end; exit Intranet.run(JSON.parse(ARGV.fetch(0)))"
    invalid.each do |args|
      out, err, status = Open3.capture3(RUBY, '-e', runner, SOURCE, JSON.generate(args))
      refute status.success?, args.inspect
      assert_empty out
      assert_match(/intranet:/, err)
      refute_includes err, 'configuration reached'
    end
  end

  def test_native_ssh_closes_the_password_fd_before_proxy_command
    marker = File.join(@home, 'fd-result')
    helper = File.join(@home, 'probe.rb')
    File.write(helper, "begin; IO.for_fd(3).stat; result = 'leaked'; rescue Errno::EBADF, ArgumentError; result = 'closed'; end; File.write(ARGV.fetch(0), result)\n")
    reader, writer = IO.pipe
    writer.close
    command = Shellwords.join([RUBY, helper, marker])
    _out, err, _status = Open3.capture3('/usr/bin/ssh', '-F', '/dev/null', '-o', "ProxyCommand=#{command.gsub('%', '%%')}", '-o', 'ConnectTimeout=2', '192.168.1.116', 3 => reader)
    assert File.exist?(marker), err
    assert_equal 'closed', File.read(marker)
  ensure
    reader.close if reader && !reader.closed?
  end

  def with_proxy(address_type: 1, auth: [1, 0], reply: 0, version: 5, reserved: 0)
    server = TCPServer.new('127.0.0.1', 0)
    @values['port'] = server.addr[1]
    save_config
    task = Thread.new do
      client = server.accept
      assert_equal [5, 1, 2], client.read(3).bytes
      [5, 2].each { |byte| client.write(byte.chr) }
      assert_equal [1, 10], client.read(2).bytes
      assert_equal 'proxy-user', client.read(10)
      length = client.read(1).unpack1('C')
      assert_equal 'invented-proxy-password', client.read(length)
      auth.each { |byte| client.write(byte.chr) }
      if auth == [1, 0]
        assert_equal [5, 1, 0, 1, 192, 168, 1, 116, 0, 22], client.read(10).bytes
        bound = { 1 => "\x7f\x00\x00\x01".b, 3 => "\x09localhost".b, 4 => "\0".b * 15 + "\1".b }.fetch(address_type, ''.b)
        response = [version, reply, reserved, address_type].pack('C*') + bound + [1234].pack('n')
        response.each_byte { |byte| client.write(byte.chr) }
        yield client if reply.zero? && version == 5 && reserved.zero? && [1, 3, 4].include?(address_type)
      end
    rescue Errno::EPIPE, Errno::ECONNRESET
      raise if auth == [1, 0] && reply.zero? && version == 5 && reserved.zero? && [1, 3, 4].include?(address_type)
    ensure
      client.close if client && !client.closed?
    end
    result = yield(:run)
    assert task.join(5), 'fake SOCKS server did not finish'
    task.value
    result
  ensure
    server.close if server && !server.closed?
    task.kill.join if task && task.alive?
  end

  def test_socks_variable_bound_addresses_and_binary_half_close
    [1, 3, 4].each do |kind|
      payload = "\x00\xffhello\x00".b
      with_proxy(address_type: kind) do |peer|
        if peer == :run
          out, err, status = Open3.capture3({ 'HOME' => @home }, RUBY, SOURCE, '--internal-proxy', '192.168.1.116', stdin_data: payload, binmode: true)
          assert status.success?, err
          assert_empty err
          assert_equal "reply\xff\x00".b + payload, out
        else
          received = peer.read
          assert_equal payload, received
          peer.write("reply\xff\x00".b + received)
        end
      end
    end
  end

  def test_socks_rejections_and_malformed_responses_stay_on_stderr
    [{ auth: [1, 1] }, { auth: [2, 0] }, { reply: 5 }, { version: 4 }, { reserved: 1 }, { address_type: 9 }].each do |options|
      with_proxy(**options) do |peer|
        next unless peer == :run
        out, err, status = invoke('--internal-proxy', '192.168.1.116')
        refute status.success?
        assert_empty out
        assert_match(/SOCKS proxy/, err)
        refute_match(/invented/, err)
      end
    end
  end

  def test_remote_eof_terminates_even_while_stdin_is_open
    with_proxy do |peer|
      next unless peer == :run
      Open3.popen3({ 'HOME' => @home }, RUBY, SOURCE, '--internal-proxy', '192.168.1.116') do |input, output, error, wait|
        assert wait.join(3), 'bridge remained blocked on stdin after remote EOF'
        assert wait.value.success?, error.read
        assert_empty output.read
        refute input.closed?
      end
    end
  end
end
