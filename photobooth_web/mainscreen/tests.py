from django.test import TestCase, Client
from django.urls import reverse


class ViewTests(TestCase):
    def setUp(self):
        self.client = Client()

    # ------------------------------------------------------------------
    # index / attract
    # ------------------------------------------------------------------

    def test_index_status(self):
        response = self.client.get(reverse("index"))
        self.assertEqual(response.status_code, 200)

    def test_index_template(self):
        response = self.client.get(reverse("index"))
        self.assertTemplateUsed(response, "index.html")

    def test_attract_status(self):
        response = self.client.get(reverse("attract"))
        self.assertEqual(response.status_code, 200)

    def test_attract_template(self):
        response = self.client.get(reverse("attract"))
        self.assertTemplateUsed(response, "attract.html")

    def test_attract_contains_image(self):
        response = self.client.get(reverse("attract"))
        self.assertContains(response, "attract_static.png")

    # ------------------------------------------------------------------
    # series_capture
    # ------------------------------------------------------------------

    def test_series_capture_status(self):
        response = self.client.get(reverse("series_capture"))
        self.assertEqual(response.status_code, 200)

    def test_series_capture_template(self):
        response = self.client.get(reverse("series_capture"))
        self.assertTemplateUsed(response, "series_capture.html")

    def test_series_capture_contains_image(self):
        response = self.client.get(reverse("series_capture"))
        self.assertContains(response, "series_capture.png")

    def test_series_capture_url(self):
        self.assertEqual(reverse("series_capture"), "/main/series_capture/")

    # ------------------------------------------------------------------
    # last_capture (review frame — layered photo + overlay)
    # ------------------------------------------------------------------

    def test_last_capture_status(self):
        response = self.client.get(reverse("last_capture"))
        self.assertEqual(response.status_code, 200)

    def test_last_capture_template(self):
        response = self.client.get(reverse("last_capture"))
        self.assertTemplateUsed(response, "last_capture.html")

    def test_last_capture_contains_photo_layer(self):
        response = self.client.get(reverse("last_capture"))
        self.assertContains(response, "last.jpg")

    def test_last_capture_contains_overlay(self):
        response = self.client.get(reverse("last_capture"))
        self.assertContains(response, "last_capture.png")

    def test_last_capture_url(self):
        self.assertEqual(reverse("last_capture"), "/main/last_capture/")

    def test_last_capture_photo_aperture_geometry(self):
        response = self.client.get(reverse("last_capture"))
        self.assertContains(response, "width: 1215px")
        self.assertContains(response, "height: 810px")
        self.assertContains(response, "top: 135px")
        self.assertContains(response, "left: 352px")
        self.assertContains(response, "object-fit: cover")

    # ------------------------------------------------------------------
    # series_final (layered photo + overlay)
    # ------------------------------------------------------------------

    def test_series_final_status(self):
        response = self.client.get(reverse("series_final"))
        self.assertEqual(response.status_code, 200)

    def test_series_final_template(self):
        response = self.client.get(reverse("series_final"))
        self.assertTemplateUsed(response, "series_final.html")

    def test_series_final_contains_photo_layer(self):
        response = self.client.get(reverse("series_final"))
        self.assertContains(response, "last.jpg")

    def test_series_final_contains_overlay(self):
        response = self.client.get(reverse("series_final"))
        self.assertContains(response, "series_final.png")

    # ------------------------------------------------------------------
    # single_final (layered photo + overlay)
    # ------------------------------------------------------------------

    def test_single_final_status(self):
        response = self.client.get(reverse("single_final"))
        self.assertEqual(response.status_code, 200)

    def test_single_final_template(self):
        response = self.client.get(reverse("single_final"))
        self.assertTemplateUsed(response, "single_final.html")

    def test_single_final_contains_photo_layer(self):
        response = self.client.get(reverse("single_final"))
        self.assertContains(response, "last.jpg")

    def test_single_final_contains_overlay(self):
        response = self.client.get(reverse("single_final"))
        self.assertContains(response, "single_final.png")

    def test_single_final_photo_aperture_geometry(self):
        response = self.client.get(reverse("single_final"))
        self.assertContains(response, "width: 1215px")
        self.assertContains(response, "height: 810px")
        self.assertContains(response, "top: 135px")
        self.assertContains(response, "left: 352px")
        self.assertContains(response, "object-fit: cover")
