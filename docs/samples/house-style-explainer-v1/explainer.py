"""Explainer deck sample: PDF and an editable PPTX from this one file. Build: publishing build docs/samples/house-style-explainer-v1
Everything here is invented: a neutral topic that shows each kind of slide the explainer format has."""
from publishing.explainer import Explainer

x = Explainer(__file__, "How a community tool shed runs", author="Example Author")

x.title("Worked example · an invented topic", "How a community tool shed runs",
        "Lend a drill on Saturday, get it back by Friday: a shed that stays stocked.", "Example Author",
        notes="This deck is an invented example. It shows every kind of slide in the explainer format: title, agenda, statement, "
              "diagram, cards, story, mapping table, contrast, two columns, section, quote and closing. The tool shed "
              "is made up, and so is every number in it.")

x.agenda("Nine parts", "From borrowing a drill to running the shed",
         [("The idea", "A shed lends tools and expects them back."), ("The loop", "Out on Saturday, back by Friday."),
          ("The jobs", "Registrar, checker and host."), ("A lesson", "One loose handle, one new rule."),
          ("The mapping", "What a tool shed borrows from a library."), ("Before and after", "From a garage to a shed."),
          ("What works", "Few rules, labelled hooks."), ("Starting out", "Three weeks from an empty garage."),
          ("The numbers", "A first year, in three figures.")],
         src="Invented example",
         notes="The agenda is a grid of numbered cards, one per part, each with a heading and a line of words. Say the "
               "order the deck will follow; it is invented, like everything in this example.")

x.statement("The point", "A tool shed lends tools, and expects them back",
            ["Neighbours <b>borrow a tool</b> for a week, free, with a name in the ledger.",
             "They use it, <b>clean it</b> and hang it back on its own hook.",
             "Every tool has a <b>ledger line</b>: what it is, its condition, who gave it.",
             "Because tools come back, the shed <b>needs no budget</b> beyond blades and oil.",
             "<span class='dim'>Nothing is sold; the only currency is a tool returned clean.</span>"],
            src="Invented example; no real shed",
            notes="Four ideas carry the deck: borrow for a week, clean it, hang it back, and the ledger line that lets the "
                  "next borrower trust the tool. All of it is an invented example.")

x.diagram("The loop in one picture", "Tools go out on Saturday and come back by Friday", "diagram.svg",
          src="Invented example; diagram drawn for this deck",
          notes="Read it left to right. Neighbours give spare tools. The ledger gets one line per tool. The shed hangs them "
                "on labelled hooks. Borrowers use them and bring them back along the top arrow. That arrow is the whole "
                "idea: it is why the hooks never stay empty.")

x.cards("Three jobs", "Three volunteers keep the shed open",
        [("The registrar", "Writes one ledger line per tool: its name, its condition and who gave it. "
                           "A tool with no line is not hung.", "accent"),
         ("The checker", "Looks at each returned tool: clean, dry, nothing loose. Anything damaged goes to the repair "
                         "bench, never back on a hook.", "detour"),
         ("The host", "Opens the shed on Saturday mornings, hands out tools and explains the one rule: "
                      "bring it back by Friday.", "hit")],
        lesson=("Why it works", "Each job is small and has one test, so a new volunteer can start in an hour."),
        src="Invented example",
        notes="The three jobs. The registrar writes ledger lines. The checker decides what is fit to hang. The host opens "
              "the shed. The lesson: every job has a single test, which is why a new volunteer is useful quickly.")

x.story("A lesson, with a made-up example", "A rule that came from one loose handle",
        sub="A hammer went out with a cracked handle.",
        what="A returned hammer was hung back on its hook with a hairline crack in the handle. A borrower swung it "
             "and the head came off.",
        why="The checker looked at the head, which was fine, and trusted the note the borrower had left.",
        fix="A returned tool is hung only after the checker has tried every moving part, "
            "and the ledger line says who checked it.",
        lesson="Test the tool with your hands, not only your eyes.",
        src="Invented example; no real incident",
        notes="This story is invented. The point is its shape: what went wrong, why it got through, and the rule that came "
              "out of it. A good story slide ends with a rule a newcomer can apply next time.")

x.map("The mapping", "A tool shed borrows its habits from a book library",
      ("Book library", "Tool shed", "Same or different?"),
      [("A catalogue entry per book", "A ledger line per tool", "same", "same idea"),
       ("A due date stamped inside", "A Friday deadline, said aloud", "differs", "looser here"),
       ("A fine for a late book", "A reminder and a cup of tea", "differs", "kinder here"),
       ("Damaged books are mended", "Damaged tools go to the bench", "same", "same idea"),
       ("A card to join", "A name in the ledger", "ahead", "simpler here"),
       ("Opening hours all week", "Saturday mornings only", "behind", "fewer hours")],
      src="Invented example",
      notes="A mapping table helps the audience reuse what they already know. Same means the habit carries over "
            "unchanged; differs means we chose another way; ahead and behind mark where the shed is simpler or thinner.")

x.contrast("Before and after", "From a shared garage to a labelled shed",
           ("Before", "Now"),
           "Tools lived in one garage. Nobody knew what was there, so people bought a second drill and the first "
           "went missing.",
           "Every tool has a hook, a ledger line and a Friday deadline, so anyone can see what is in and what is out.",
           [("Finding", "A shelf of hooks, each labelled with the tool's name."),
            ("Trusting", "A ledger line says its condition and who checked it last."),
            ("Returning", "A tool hung back clean is the only sign-off it needs.")],
           src="Invented example",
           notes="The contrast has two cards, then three small examples of the change in practice. Say the before in one "
                 "breath, the now in one breath, and let the examples carry the detail.")

x.twocol("What works, what does not", "Keep the rules few and the hooks labelled",
         ("What works", "hit", ["A hook for every tool", "A ledger line for every hook",
                                "One rule said out loud", "Saturday mornings, always"]),
         ("What does not", "red", ["Tools with no home", "Rules on a long notice board",
                                   "Fines nobody collects", "Opening whenever someone is free"]),
         src="Invented example",
         notes="Two columns, one for what works and one for what does not. Keep each list to four short lines.")

x.section("Part two", "Starting your own", "Three weeks from an empty garage to an open shed.", number="2",
          notes="A section slide marks a change of subject. Say what comes next in one sentence.")

x.quote("In their words", "What a first-time borrower said",
        "I came for a ladder and left with <span class='em'>the confidence</span> to ask for a second tool next week.",
        who="An invented borrower",
        src="Invented example; no real person",
        notes="A quote slide: read it slowly, then say why it matters. This quote is invented.")

x.closing("To remember", "A shed runs on returns",
          "Three numbers from an invented shed in its first year.",
          [("40", "tools given by neighbours in the first month"),
           ("312", "loans in the year, all of them returned"),
           ("1", "volunteer hour to learn any of the three jobs")],
          src="Invented example; every figure is made up",
          notes="Close on the three figures. They are invented: forty tools, three hundred and twelve loans, and one hour "
                "to learn a job.")

TITLE, S, NOTES, AUTHOR = x.TITLE, x.S, x.NOTES, x.AUTHOR
