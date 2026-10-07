"""Explainer deck for {name}: a PDF and an editable PPTX from this one file. Build: publishing build {rel}
Every slide carries `notes` (what the presenter says) and, for the small print, `src` (it also ends the notes)."""
from publishing.explainer import Explainer

x = Explainer(__file__, "Title of the explainer", author="Your Name")

x.title("{kicker}", "Title of the explainer", "One sentence that says what this explains.", "Your Name",
        notes="Say what this deck explains and who it is for, in two sentences.")

x.statement("The point", "One sentence the audience should keep",
            ["<b>First idea.</b> Plain English, one idea per line.",
             "<b>Second idea.</b> What follows from it.",
             "<span class='dim'>A quieter closing line.</span>"],
            src="Say where the evidence comes from",
            notes="Walk the three lines in order; the first is the one to remember.")

x.diagram("The picture", "One simple diagram", "diagram.svg",
          src="Diagram: drawn for this deck",
          notes="Read it left to right, one box at a time, and say what moves between them.")

x.closing("To remember", "What to take away", "One line that closes the loop.",
          [("1", "The first thing."), ("2", "The second thing."), ("3", "The third thing.")],
          src="Say where the figures come from",
          notes="Close on the three takeaways and ask for the decision, if there is one.")

TITLE, S, NOTES, AUTHOR = x.TITLE, x.S, x.NOTES, x.AUTHOR
