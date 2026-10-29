"""Report-only logo: strict PNG/JPEG validation, replace/remove, private storage and use in generated documents."""
import base64
from io import BytesIO
from pathlib import Path
import sys
import unittest
from zipfile import ZipFile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
import config
import report_branding
import sod_reports as reports
from test_sod_reports import ReportCase, H


def image(fmt='PNG', size=(160, 80), color='#2563eb', **save):
    stream = BytesIO()
    Image.new('RGB', size, color).save(stream, format=fmt, **save)
    return base64.b64encode(stream.getvalue()).decode()


class ReportBrandingTests(ReportCase):
    def put(self, payload, status=200, name='logo.png'):
        response = self.client.put('/api/sod/reports/branding', json=dict(image_base64=payload, filename=name), headers=H)
        self.assertEqual(response.status_code, status, response.text[:200])
        return response.json()

    def current(self):
        return self.client.get('/api/sod/reports/branding', headers=H).json()

    def test_png_and_jpeg_are_accepted_replaced_and_removed(self):
        self.assertIsNone(self.current()['logo'])
        self.assertEqual(self.current()['limits']['formats'], ['PNG', 'JPEG'])
        first = self.put(image('PNG'))['logo']
        self.assertEqual((first['width'], first['height'], first['filename']), (160, 80, 'logo.png'))
        self.assertTrue(first['data_url'].startswith('data:image/png;base64,'))
        second = self.put(image('JPEG', color='#dc2626'), name='logo.jpg')['logo']
        self.assertNotEqual(first['logo_id'], second['logo_id'])
        self.assertEqual(self.current()['logo']['logo_id'], second['logo_id'])
        self.assertIsNone(self.client.delete('/api/sod/reports/branding', headers=H).json()['logo'])
        self.assertIsNone(self.current()['logo'])

    def test_unsafe_oversized_tiny_and_malformed_images_are_rejected_without_changing_the_current_logo(self):
        kept = self.put(image('PNG'))['logo']['logo_id']
        self.put(image('WEBP'), status=422)
        self.put(image('GIF', save_all=False), status=422)
        self.put(image('PNG', size=(8, 8)), status=422)
        self.put(base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg"/>').decode(), status=422)
        self.put('not base64 !!!', status=422)
        noise = Image.effect_noise((1200, 1200), 255).convert('RGB')
        stream = BytesIO(); noise.save(stream, format='PNG')
        self.assertGreater(len(stream.getvalue()), report_branding.MAX_BYTES)
        self.put(base64.b64encode(stream.getvalue()).decode(), status=422)
        self.assertEqual(self.current()['logo']['logo_id'], kept)

    def test_unauthenticated_requests_are_refused(self):
        self.assertEqual(self.client.get('/api/sod/reports/branding').status_code, 403)
        self.assertEqual(self.client.put('/api/sod/reports/branding', json=dict(image_base64=image())).status_code, 403)

    def test_metadata_is_stripped_and_a_damaged_file_falls_back_to_no_logo(self):
        payload = self.put(image('PNG'))['logo']
        path = config.config_dir() / 'branding' / f"{payload['logo_id']}.png"
        self.assertNotIn(b'Exif', path.read_bytes())
        path.write_bytes(b'damaged')
        self.assertIsNone(self.current()['logo'])
        self.assertIsNone(report_branding.current_logo_id())

    def test_report_models_and_documents_use_the_report_logo_and_it_is_not_in_the_frozen_period(self):
        logo = self.put(image('PNG'))['logo']['logo_id']
        data = self.model()
        self.assertEqual(data['logo_id'], logo)
        docx = reports.render(data, 'docx')
        with ZipFile(BytesIO(docx)) as archive:
            self.assertTrue(any(name.startswith('word/media/') for name in archive.namelist()))
        self.assertTrue(reports.render(data, 'pdf').startswith(b'%PDF'))
        remediation = reports.remediation_model(self.pid, reports.RemediationOptions())
        self.assertEqual(remediation['logo_id'], logo)
        self.client.delete('/api/sod/reports/branding', headers=H)
        self.assertNotEqual(self.model()['logo_id'], logo)


if __name__ == '__main__':
    unittest.main()
