import argparse
import socket
import struct
import sys

import sounddevice as sd

HOST = '0.0.0.0'
DEFAULT_PORT = 9000
CHUNK_SIZE = 4096


def parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f'无效的端口号: {value}')
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(f'端口号需在 1-65535 之间: {port}')
    return port


def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        return s.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        s.close()


def recv_exact(conn: socket.socket, size: int) -> bytes:
    buf = b''
    while len(buf) < size:
        chunk = conn.recv(size - len(buf))
        if not chunk:
            raise ConnectionError('设备已断开连接')
        buf += chunk
    return buf


def handle_client(conn: socket.socket, addr: tuple) -> None:
    print(f'设备已连接: {addr[0]}:{addr[1]}')
    stream = None
    try:
        header = recv_exact(conn, 16)
        magic, rate, channels, bits = struct.unpack('<8sIHH', header)
        if not magic.startswith(b'HMAUDIO'):
            raise ValueError(f'无效的流头部: {magic!r}')
        print(f'音频格式: {rate} Hz / {channels} 声道 / {bits} bit PCM')
        stream = sd.RawOutputStream(
            samplerate=rate,
            channels=channels,
            dtype='int16',
            blocksize=1024,
        )
        stream.start()
        while True:
            data = recv_exact(conn, CHUNK_SIZE)
            stream.write(data)
    except (ConnectionError, OSError) as e:
        print(f'设备断开: {e}')
    except ValueError as e:
        print(f'错误: {e}', file=sys.stderr)
    finally:
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except OSError:
                pass
        try:
            conn.close()
        except OSError:
            pass


def port_in_use(port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.5)
        return probe.connect_ex(('127.0.0.1', port)) == 0
    except OSError:
        return False
    finally:
        probe.close()


def suggest_free_port(port: int) -> int:
    for candidate in range(port + 1, min(port + 101, 65536)):
        if not port_in_use(candidate):
            return candidate
    return 0


def create_server(port: int) -> socket.socket:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Windows 下的 SO_REUSEADDR 允许抢占已监听端口，改用独占选项确保端口冲突能被发现
    if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        server.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((HOST, port))
    except OSError as e:
        server.close()
        raise RuntimeError(f'端口 {port} 无法绑定: {e}')
    server.listen(1)
    return server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='接收鸿蒙设备发送的音频流并通过声卡播放')
    parser.add_argument(
        'port',
        nargs='?',
        type=parse_port,
        default=DEFAULT_PORT,
        help=f'监听端口，取值范围 1-65535，默认 {DEFAULT_PORT}')
    return parser.parse_args()


def main() -> None:
    port = parse_args().port
    if port_in_use(port):
        alternative = suggest_free_port(port)
        hint = f'，可改用端口 {alternative}' if alternative else ''
        print(f'错误: 端口 {port} 已被其他程序占用，请更换端口后重试{hint}')
        print(f'用法: python pc_audio_receiver.py [端口]，默认端口 {DEFAULT_PORT}')
        sys.exit(1)

    try:
        server = create_server(port)
    except RuntimeError as e:
        print(f'错误: {e}')
        print(f'请更换端口后重试，例如: python pc_audio_receiver.py {port + 1}')
        sys.exit(1)

    print(f'本机 IP: {get_local_ip()}  端口: {port}')
    print('请在鸿蒙设备 App 中输入上面的 IP 和端口, 然后点击"开始传输"')
    print(f'设备断开后会自动继续监听端口 {port}, 按 Ctrl+C 退出程序')
    try:
        while True:
            print('等待设备连接 ...')
            try:
                conn, addr = server.accept()
            except OSError:
                break
            handle_client(conn, addr)
            print('已断开, 回到监听状态')
    except KeyboardInterrupt:
        print('\n正在退出 ...')
    finally:
        server.close()
        print('已停止')


if __name__ == '__main__':
    main()
