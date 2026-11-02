from pathlib import Path
import subprocess
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/nginx-route.awk'

class ProxyHeaderTests(unittest.TestCase):
    def route(self, text):
        return subprocess.run(['awk','-v','action=install','-v','prefix=/poe2guild','-v','bind=127.0.0.1:9002','-v','server_name=dyyyl.ovh','-f',str(SCRIPT)],input=text,text=True,capture_output=True)

    def test_upgrade_existing_route_preserves_other_services_and_is_idempotent(self):
        text='''server {
server_name dyyyl.ovh;
location /other/ { proxy_pass http://127.0.0.1:9001/; }
location /poe2guild/ { proxy_pass http://127.0.0.1:9002/; }
location = /poe2guild { return 301 /poe2guild/; }
}'''
        result=self.route(text)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('proxy_set_header X-Forwarded-Proto $scheme;',result.stdout)
        self.assertIn('location /other/ { proxy_pass http://127.0.0.1:9001/; }',result.stdout)
        self.assertEqual(self.route(result.stdout).stdout,result.stdout)

    def test_certbot_redirect_block_is_preserved(self):
        text='''server { listen 80; server_name dyyyl.ovh; return 301 https://$host$request_uri; }
server { listen 443 ssl; server_name dyyyl.ovh;
location /poe2guild/ { proxy_pass http://127.0.0.1:9002/; }
}'''
        result=self.route(text)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn(text.splitlines()[0],result.stdout)
        self.assertEqual(self.route(result.stdout).stdout,result.stdout)

    def test_ambiguous_application_hosts_fail_without_partial_output(self):
        block='server { server_name dyyyl.ovh; location /poe2guild/ { proxy_pass http://127.0.0.1:9002/; } }\n'
        result=self.route(block+block)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(result.stdout,'')
