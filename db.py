import sqlite3, os, uuid, datetime

DB = os.path.expanduser("~/.local/share/blocknotes/data.db")
os.makedirs(os.path.dirname(DB), exist_ok=True)

def init():
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS notes (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, created TEXT, modified TEXT
    );
    CREATE TABLE IF NOT EXISTS blocks (
        id TEXT PRIMARY KEY, text TEXT NOT NULL, deleted INTEGER DEFAULT 0,
        created TEXT, modified TEXT
    );
    CREATE TABLE IF NOT EXISTS note_blocks (
        note_id TEXT, block_id TEXT, position INTEGER, transcluded INTEGER DEFAULT 0,
        PRIMARY KEY (note_id, block_id),
        FOREIGN KEY (note_id) REFERENCES notes(id),
        FOREIGN KEY (block_id) REFERENCES blocks(id)
    );
    """)
    c.commit()
    return c

def now():
    return datetime.datetime.now().isoformat(timespec="seconds")

# Notes
def create_note(title="Untitled"):
    c = init(); nid = str(uuid.uuid4())
    c.execute("INSERT INTO notes VALUES (?,?,?,?)", (nid, title, now(), now()))
    c.commit(); c.close(); return nid

def delete_note(nid):
    c = init()
    c.execute("DELETE FROM note_blocks WHERE note_id=?", (nid,))
    c.execute("DELETE FROM notes WHERE id=?", (nid,))
    c.commit(); c.close()

def list_notes():
    c = init()
    rows = c.execute("SELECT id, title FROM notes ORDER BY modified DESC").fetchall()
    c.close(); return rows

def rename_note(nid, title):
    c = init(); c.execute("UPDATE notes SET title=?, modified=? WHERE id=?", (title, now(), nid))
    c.commit(); c.close()

# Blocks
def create_block(text="", note_id=None):
    c = init(); bid = str(uuid.uuid4())
    c.execute("INSERT INTO blocks VALUES (?,?,?,?,?)", (bid, text, 0, now(), now()))
    if note_id:
        pos = c.execute("SELECT COALESCE(MAX(position),-1)+1 FROM note_blocks WHERE note_id=?", (note_id,)).fetchone()[0]
        c.execute("INSERT INTO note_blocks VALUES (?,?,?,0)", (note_id, bid, pos))
    c.commit(); c.close(); return bid

def get_block(bid):
    c = init(); r = c.execute("SELECT id, text, deleted FROM blocks WHERE id=?", (bid,)).fetchone()
    c.close(); return r

def edit_block(bid, text):
    c = init(); c.execute("UPDATE blocks SET text=?, modified=? WHERE id=?", (text, now(), bid))
    c.commit(); c.close()

def delete_block(bid):
    c = init(); c.execute("UPDATE blocks SET deleted=1, modified=? WHERE id=?", (now(), bid))
    c.commit(); c.close()

def split_block(bid, pos):
    c = init()
    b = c.execute("SELECT text FROM blocks WHERE id=?", (bid,)).fetchone()
    if not b: c.close(); return None
    text = b[0]
    left = text[:pos]; right = text[pos:]
    new_id = str(uuid.uuid4())
    c.execute("INSERT INTO blocks VALUES (?,?,?,?,?)", (new_id, right, 0, now(), now()))
    c.execute("UPDATE blocks SET text=?, modified=? WHERE id=?", (left, now(), bid))
    # insert new block after bid in all notes that contain bid
    for note_id, position, transcluded in c.execute("SELECT note_id, position, transcluded FROM note_blocks WHERE block_id=?", (bid,)).fetchall():
        # shift positions
        c.execute("UPDATE note_blocks SET position=position+1 WHERE note_id=? AND position>?", (note_id, position))
        c.execute("INSERT INTO note_blocks VALUES (?,?,?,?)", (note_id, new_id, position+1, transcluded))
    c.commit(); c.close(); return new_id

def merge_blocks(bid_a, bid_b):
    c = init()
    a = c.execute("SELECT text FROM blocks WHERE id=?", (bid_a,)).fetchone()
    b = c.execute("SELECT text FROM blocks WHERE id=?", (bid_b,)).fetchone()
    if not a or not b: c.close(); return None
    new_id = str(uuid.uuid4())
    c.execute("INSERT INTO blocks VALUES (?,?,?,?,?)", (new_id, a[0]+"\n"+b[0], 0, now(), now()))
    # replace in notes: where both adjacent? just replace bid_a with new_id, remove bid_b
    for note_id in [r[0] for r in c.execute("SELECT DISTINCT note_id FROM note_blocks WHERE block_id IN (?,?)", (bid_a, bid_b)).fetchall()]:
        # find position of bid_a
        pos = c.execute("SELECT position FROM note_blocks WHERE note_id=? AND block_id=?", (note_id, bid_a)).fetchone()
        if pos:
            c.execute("UPDATE note_blocks SET block_id=? WHERE note_id=? AND block_id=?", (new_id, note_id, bid_a))
            c.execute("DELETE FROM note_blocks WHERE note_id=? AND block_id=?", (note_id, bid_b))
    # tombstone old
    c.execute("UPDATE blocks SET deleted=1, modified=? WHERE id IN (?,?)", (now(), bid_a, bid_b))
    c.commit(); c.close(); return new_id

def move_block(bid, from_note, to_note, new_pos):
    c = init()
    c.execute("DELETE FROM note_blocks WHERE note_id=? AND block_id=?", (from_note, bid))
    # shift
    c.execute("UPDATE note_blocks SET position=position+1 WHERE note_id=? AND position>=?", (to_note, new_pos))
    # determine transcluded: if block already native elsewhere, this is transcluded
    native_exists = c.execute("SELECT COUNT(*) FROM note_blocks WHERE block_id=? AND transcluded=0", (bid,)).fetchone()[0]
    trans = 1 if native_exists > 0 else 0
    c.execute("INSERT OR REPLACE INTO note_blocks VALUES (?,?,?,?)", (to_note, bid, new_pos, trans))
    c.commit(); c.close()

def transclude(bid, into_note, pos):
    c = init()
    c.execute("UPDATE note_blocks SET position=position+1 WHERE note_id=? AND position>=?", (into_note, pos))
    c.execute("INSERT OR REPLACE INTO note_blocks VALUES (?,?,?,1)", (into_note, bid, pos))
    c.commit(); c.close()

def note_blocks_list(nid):
    c = init()
    rows = c.execute("""SELECT nb.block_id, nb.transcluded, b.text, b.deleted
        FROM note_blocks nb JOIN blocks b ON b.id=nb.block_id
        WHERE nb.note_id=? ORDER BY nb.position""", (nid,)).fetchall()
    c.close(); return rows

def backlinks(bid):
    c = init()
    rows = c.execute("SELECT note_id FROM note_blocks WHERE block_id=? AND transcluded=1", (bid,)).fetchall()
    c.close(); return [r[0] for r in rows]
