"""Display the actual rendered PDF or the current source inside a native widget."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QScrollArea, QStackedWidget, QVBoxLayout, QWidget


def plain_label(text="", name=""):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    if name:
        label.setObjectName(name)
    return label


def source_page(profile):
    page = QWidget()
    page.setObjectName("sourcePage")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(28, 25, 28, 28)
    layout.setSpacing(7)
    layout.addWidget(plain_label(profile.name, "paperName"))
    layout.addWidget(plain_label(profile.contact, "paperContact"))
    layout.addSpacing(7)
    layout.addWidget(plain_label("Experience", "paperHeading"))
    for role in profile.roles:
        layout.addWidget(plain_label(role.company, "paperEmployer"))
        details = (role.title, role.location, role.dates)
        layout.addWidget(plain_label("   ·   ".join(s for s in details if s), "paperContact"))
        for bullet in role.bullets:
            layout.addWidget(plain_label("•   " + bullet.text))
        layout.addSpacing(6)
    for title, content in [
        ("Skills", ", ".join(profile.skills)),
        ("Certifications", profile.certifications),
        ("Education", "\n".join(" · ".join(s for s in (e.institution, e.degree, e.dates, e.detail) if s)
                                  for e in profile.education)),
        ("Interests", profile.interests),
    ]:
        if content:
            layout.addWidget(plain_label(title, "paperHeading"))
            layout.addWidget(plain_label(content))
    layout.addStretch()
    return page


class PagePreview(QStackedWidget):
    def __init__(self):
        super().__init__()
        self.source = QScrollArea()
        self.source.setWidgetResizable(True)
        self.addWidget(self.source)
        self.pdf = QScrollArea()
        self.pdf.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.pdf.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.pdf.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.paper = QLabel()
        self.paper.setObjectName("pdfPreview")
        self.paper.setAccessibleName("Rendered resume page")
        self.pdf.setWidget(self.paper)
        self.addWidget(self.pdf)
        self.original = None

    def show_source(self, profile):
        self.original = None
        self.paper.clear()
        self.source.setWidget(source_page(profile))
        self.setCurrentWidget(self.source)

    def show_pdf(self, path):
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(str(path)) as document:
            page = document[0]
            try:
                bitmap = page.render(scale=2)
                try:
                    with bitmap.to_pil().convert("RGB") as pixels:
                        image = QImage(pixels.tobytes(), pixels.width, pixels.height,
                                       3 * pixels.width, QImage.Format.Format_RGB888).copy()
                finally:
                    bitmap.close()
            finally:
                page.close()
        self.original = QPixmap.fromImage(image)
        self.setCurrentWidget(self.pdf)
        self.fit_width()
        self.pdf.verticalScrollBar().setValue(0)

    def fit_width(self):
        if self.original is None:
            return
        width = max(100, min(self.original.width(), self.pdf.viewport().width() - 12))
        pixmap = self.original.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
        self.paper.setPixmap(pixmap)
        self.paper.resize(pixmap.size())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_width()
