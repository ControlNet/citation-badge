import unittest

from bs4 import BeautifulSoup
from scholarly.data_types import PublicationSource
from scholarly.publication_parser import PublicationParser

import main  # noqa: F401  (installs the author-line parser patch)


PROFILE_ROW = """
<tr class="gsc_a_tr">
  <td class="gsc_a_t">
    <a href="/citations?view_op=view_citation&hl=en&user=id1&citation_for_view=id1:abc123"
       class="gsc_a_at">Example Paper</a>
    <div class="gs_gray">Z Cai, S Ghosh, A Dhall, ...</div>
    <div class="gs_gray">CVPR, 2023<span class="gs_oph">, 2023</span></div>
  </td>
  <td class="gsc_a_c">
    <a href="https://scholar.google.com/scholar?oi=bibs&cites=123" class="gsc_a_ac gs_ibl">10</a>
  </td>
  <td class="gsc_a_y"><span class="gsc_a_h gsc_a_hc gs_ibl">2023</span></td>
</tr>
"""


def parse_row(html):
    row = BeautifulSoup(html, "html.parser").find("tr")
    return PublicationParser(nav=None).get_publication(
        row, PublicationSource.AUTHOR_PUBLICATION_ENTRY
    )


class AuthorLineTest(unittest.TestCase):
    def test_profile_row_keeps_author_line(self):
        pub = parse_row(PROFILE_ROW)

        self.assertEqual(pub["bib"]["author_line"], "Z Cai, S Ghosh, A Dhall, ...")
        self.assertEqual(pub["bib"]["citation"], "CVPR, 2023, 2023")
        self.assertEqual(pub["num_citations"], 10)

    def test_profile_row_without_gray_lines_has_empty_author_line(self):
        html = PROFILE_ROW.replace('class="gs_gray"', 'class="other"')

        pub = parse_row(html)

        self.assertEqual(pub["bib"]["author_line"], "")


if __name__ == "__main__":
    unittest.main()
