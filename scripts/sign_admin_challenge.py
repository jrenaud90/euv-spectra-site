#!/usr/bin/env python3

import argparse
import base64
import getpass
import sys

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa


def load_private_key(key_path, password_text=None):
    with open(key_path, 'rb') as key_file:
        key_bytes = key_file.read()

    if key_bytes.startswith(b'PuTTY-User-Key-File-'):
        raise ValueError('PuTTY .ppk files are not supported directly. Export the private key as PEM or OpenSSH first.')

    password = password_text.encode('utf-8') if password_text else None
    loaders = (
        serialization.load_pem_private_key,
        serialization.load_ssh_private_key,
    )
    last_error = None
    for loader in loaders:
        try:
            return loader(key_bytes, password=password)
        except (TypeError, ValueError) as exc:
            last_error = exc

    raise ValueError('Unsupported private key format. Use a PEM or OpenSSH private key.') from last_error


def sign_challenge(private_key, challenge_text):
    message = challenge_text.encode('utf-8')
    if isinstance(private_key, ed25519.Ed25519PrivateKey):
        return private_key.sign(message)
    if isinstance(private_key, rsa.RSAPrivateKey):
        return private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    if isinstance(private_key, ec.EllipticCurvePrivateKey):
        return private_key.sign(message, ec.ECDSA(hashes.SHA256()))
    raise ValueError(f'Unsupported private key type: {type(private_key).__name__}')


def parse_args():
    parser = argparse.ArgumentParser(
        description='Sign a PEGASUS admin login challenge and print the base64 signature.'
    )
    parser.add_argument(
        '--key',
        '--private-key',
        dest='key',
        required=True,
        help='Path to the PEM or OpenSSH private key used for admin login.',
    )
    parser.add_argument(
        'challenge_arg',
        nargs='?',
        help='Challenge text copied from /apps/pegasus/admin/login.',
    )
    parser.add_argument('--challenge', help='Challenge text copied from /apps/pegasus/admin/login.')
    parser.add_argument(
        '--challenge-file',
        help='Path to a file containing the challenge text. Useful when pasting multi-line input via a file.',
    )
    parser.add_argument('--password', help='Private key password. Omit to be prompted when the key is encrypted.')
    parser.add_argument(
        '--label',
        action='store_true',
        help='Print a label before the base64 signature instead of printing only the pasteable value.',
    )
    return parser.parse_args()


def get_challenge_text(args):
    provided_sources = [
        bool(args.challenge_arg),
        bool(args.challenge),
        bool(args.challenge_file),
    ]
    if sum(provided_sources) > 1:
        raise ValueError('Use only one of: positional challenge, --challenge, or --challenge-file.')

    if args.challenge_arg:
        return args.challenge_arg
    if args.challenge:
        return args.challenge
    if args.challenge_file:
        with open(args.challenge_file, 'r', encoding='utf-8') as challenge_file:
            return challenge_file.read().strip()

    challenge_text = input('Paste the admin challenge: ').strip()
    if not challenge_text:
        raise ValueError('Challenge text is required.')
    return challenge_text


def get_password_text(args):
    if args.password is not None:
        return args.password
    return None


def main():
    args = parse_args()
    try:
        challenge_text = get_challenge_text(args)
        password_text = get_password_text(args)
        try:
            private_key = load_private_key(args.key, password_text=password_text)
        except TypeError:
            if password_text is not None:
                raise
            prompt_password = getpass.getpass('Private key password: ')
            private_key = load_private_key(args.key, password_text=prompt_password)

        signature = sign_challenge(private_key, challenge_text)
        encoded_signature = base64.b64encode(signature).decode('ascii')
    except Exception as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1

    if args.label:
        print('Base64 signature:')
    print(encoded_signature)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())