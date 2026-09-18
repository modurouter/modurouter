# Korean document regression fixtures

These documents contain original synthetic content generated for this repository.
They contain no customer data. They may be redistributed with the project.

On 2026-09-18, the original DOCX, XLSX and PPTX files were opened and saved by
LibreOffice 7.4.7 in the same Debian Bookworm image used for deployment.
The DOC, XLS, PPT, ODT and RTF files are native LibreOffice exports. The committed
DOCX, XLSX and PPTX files were reopened from these exports and saved again.
This tests actual application-produced containers, not renamed text files.

The report contains Korean paragraphs, two table rows, a text box, a footnote,
a header and a footer. The workbook contains three sheets (one hidden), dates,
custom currency formats and cached formula results. The presentation contains
three slides, a table and speaker notes. Text files exercise Markdown, HTML,
quoted CSV/TSV fields, UTF-8 BOM and CP949.

Known answers and ordering are in `test_document_fixtures_issue6.py`.
The fixture source generator is `generate_documents.py` in this directory. Run it in a temporary copy of this directory, then round-trip its Office outputs through LibreOffice before replacing committed native fixtures.
Legacy extraction requires the Linux conversion dependencies in `server/Dockerfile`;
those tests are skipped on macOS and run separately in the deployment image.

The LibreOffice RTF export omits the source VML text box before extraction. Its native file does not contain the `다솜303` marker, so that marker is asserted for DOC, DOCX and ODT only. RTF coverage checks the text, table and footnote that actually exist in the native file. Conversion may omit unsupported embedded objects; preview and model sources disclose this limit.
