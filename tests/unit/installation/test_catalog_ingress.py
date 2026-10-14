"""Catalog routes survive both installer rendering and address worker activation."""

from pathlib import Path
import unittest

from core.installation.catalog_ingress import render_catalog_locations
from core.installation.host_configuration import render_nginx
from core.shared.installer import render_install_plan
from tests.unit.shared.test_installer_systemd import _make_config


class CatalogIngressTests(unittest.TestCase):
    def test_exact_static_routes_have_separate_cache_contracts(self):
        root = Path('/projects/loopino')
        locations = render_catalog_locations(root)
        self.assertIn('location = /catalog/api/apps', locations)
        self.assertIn('add_header Cache-Control "no-cache"', locations)
        self.assertIn('[a-f0-9]{64}', locations)
        self.assertIn('immutable', locations)
        self.assertIn('location /catalog/ { return 404; }', locations)
        self.assertNotIn('proxy_pass', locations)
        self.assertNotIn('autoindex on', locations)
        for path in (Path('relative'),Path('/projects/loopino;injected')):
            with self.assertRaises(ValueError):
                render_catalog_locations(path)

    def test_installer_and_worker_mount_the_same_main_origin_catalog(self):
        root = Path(__file__).resolve().parents[3]
        from dataclasses import replace
        config = replace(_make_config(root), local_only=False, hostname='loopino.example.test',
                         public_scheme='https', nginx_conf_path=root / 'tmp/nginx.conf')
        plan = render_install_plan(config, force_https_nginx=True)
        self.assertIn(render_catalog_locations(root), plan[config.nginx_conf_path])
        certificates = {kind:{'fullchain':'/test/fullchain.pem','private_key':'/test/privkey.pem'} for kind in ('main','apps')}
        rendered = render_nginx('loopino.example.test',certificates,8014,repository_root=root)
        self.assertEqual(rendered.count('location = /catalog/api/apps'),1)
        self.assertNotIn('default_server',rendered)
        self.assertEqual(rendered.count('location ^~ /.well-known/acme-challenge/'), 2)
        self.assertIn(f'root {root}/data/acme-webroot;', rendered)
        self.assertIn(f'root {root}/data/browser-origin-acme;', rendered)
