import sqlite3, random, json
from datetime import datetime, timedelta

DB_NAME = "flashcards.db"


def create_tables():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    # Create a table for flashcards
    cur.execute("""
        CREATE TABLE IF NOT EXISTS flashcards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            korean TEXT NOT NULL,
            uzbek TEXT NOT NULL,
            last_reviewed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            difficulty INTEGER DEFAULT 0,
            next_review TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            interval INTEGER DEFAULT 1
        )
        """)

    # Table for user progress
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_progress (
            user_id INTEGER PRIMARY KEY,
            words_added INTEGER DEFAULT 0,
            words_reviewed INTEGER DEFAULT 0,
            correct_answers INTEGER DEFAULT 0
        )
        """)

    # Table for leaderboard
    cur.execute("""
            CREATE TABLE IF NOT EXISTS leaderboard (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                score INTEGER DEFAULT 0
            )
            """)

    # Table for grammar
    cur.execute("""
            CREATE TABLE IF NOT EXISTS grammar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT CHECK(level IN ('Beginner', 'Intermediate', 'Advanced')),
                title TEXT NOT NULL,
                explanation TEXT NOT NULL,
                examples TEXT NOT NULL
            )
            """)

    conn.commit()
    conn.close()


# Call the function to add grammar rules
def add_flashcard(user_id, words):
    """ Adds multiple flashcards and updates user progress """
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    next_review = datetime.now()  # Review immediately

    # Insert words as a batch
    cur.executemany("INSERT INTO flashcards (user_id, korean, uzbek, next_review) VALUES (?, ?, ?, ?)",
                    [(user_id, korean, uzbek, next_review) for korean, uzbek in words])

    # Ensure user exists in user_progress
    cur.execute("""
        INSERT INTO user_progress (user_id, words_added, words_reviewed, correct_answers) 
        VALUES (?, 0, 0, 0)
        ON CONFLICT(user_id) DO NOTHING
    """, (user_id,))

    # Dynamically update words_added count based on the number of words added
    words_count = len(words)
    cur.execute("""
        UPDATE user_progress 
        SET words_added = words_added + ?
        WHERE user_id = ?
    """, (words_count, user_id))

    conn.commit()
    conn.close()


def word_exists(user_id, korean):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM flashcards WHERE user_id = ? AND korean = ?", (user_id, korean))
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def add_user(user_id):
    """ Insert a new user into the user_progress table if not exists. """
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("SELECT user_id FROM user_progress WHERE user_id = ?", (user_id,))
    user = cur.fetchone()

    if user is None:
        cur.execute("""
        INSERT INTO user_progress (user_id, words_added, words_reviewed, correct_answers)
        VALUES (?, 0, 0, 0)
        """, (user_id,))
        conn.commit()
        print(f"✅ New user {user_id} added to `user_progress`.")

    conn.close()


def get_due_flashcard(user_id, limit=10):
    """ Fetch flashcards for review. Ensure they can be reviewed multiple times a day. """
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
        SELECT id, korean, uzbek FROM flashcards
        WHERE user_id = ? 
        ORDER BY last_reviewed ASC 
        LIMIT ?
    """, (user_id, limit))

    flashcards = cur.fetchall()
    conn.close()

    return flashcards


def get_users_with_due_flashcards():
    """ Get a list of users who have flashcards due for review """
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
    SELECT DISTINCT user_id FROM flashcards 
    WHERE next_review <= CURRENT_TIMESTAMP
    """)

    users = [row[0] for row in cur.fetchall()]
    conn.close()
    return users


def get_random_words(user_id, limit=3):
    """ Retrieves a few random words for a daily challenge """
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, korean, uzbek FROM flashcards 
        WHERE user_id = ? 
        ORDER BY RANDOM() 
        LIMIT ?
    """, (user_id, limit))

    result = cur.fetchall()
    conn.close()
    return result


def get_random_wrong_answers(correct_answer, limit=3):
    """Fetches random incorrect answers from the database."""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
        SELECT DISTINCT uzbek FROM flashcards 
        WHERE uzbek != ? 
        ORDER BY RANDOM() 
        LIMIT ?
    """, (correct_answer, limit))

    wrong_answers = [row[0] for row in cur.fetchall()]
    conn.close()

    if len(wrong_answers) >= limit:
        return random.sample(wrong_answers, limit)

        # If not enough unique answers, allow repetition
    while len(wrong_answers) < limit:
        wrong_answers.append(random.choice(wrong_answers) if wrong_answers else "Nomaʼlum")

    return wrong_answers


def get_user_progress(user_id):
    """ Get user progress statistics """
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
    SELECT words_added, words_reviewed, correct_answers FROM user_progress 
    WHERE user_id = ?
    """, (user_id,))

    result = cur.fetchone()
    conn.close()

    if result:
        words_added, words_reviewed, correct_answers = result
        accuracy = round((correct_answers / words_reviewed) * 100, 2) if words_reviewed > 0 else 0
        return words_added, words_reviewed, correct_answers, accuracy
    return 0, 0, 0, 0  # Default if no data


def get_top_users(limit=10):
    """ Fetch top users sorted by score """
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
        SELECT username, score FROM leaderboard
        ORDER BY score DESC
        LIMIT ?
    """, (limit,))

    top_users = cur.fetchall()
    conn.close()

    return top_users


#         UPDATING DATA

def update_user_score(user_id, username, points):
    """ Updates the user's score, adding points """
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO leaderboard (user_id, username, score)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET score = score + ?
    """, (user_id, username, points, points))

    conn.commit()
    conn.close()


def update_flashcard_review(flashcard_id, correct):
    """ Update flashcard interval and next review date. """
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    if correct:
        cur.execute("""
                UPDATE flashcards 
                SET last_reviewed = date('now'), 
                    correct_streak = correct_streak + 1,
                    interval = CASE 
                        WHEN correct_streak >= 5 THEN interval * 2  -- Increase more if very familiar
                        ELSE interval + 1  -- Increase normally
                    END
                WHERE id = ?
            """, (flashcard_id,))
    else:
        cur.execute("""
                UPDATE flashcards 
                SET last_reviewed = date('now'), 
                    correct_streak = 0,  -- Reset streak
                    interval = 1  -- Reset interval
                WHERE id = ?
            """, (flashcard_id,))

    conn.commit()
    conn.close()


def update_difficulty(flashcard_id, difficulty):
    """ Updates difficulty level and adjusts next review using an SRS algorithm """
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    # SM2-based review intervals
    review_intervals = {1: 1, 2: 3, 3: 7}  # Hard: 1 day, Medium: 3 days, Easy: 7 days

    # Get current interval
    cur.execute("SELECT interval FROM flashcards WHERE id = ?", (flashcard_id,))
    result = cur.fetchone()
    current_interval = result[0] if result else 1

    # Update interval based on difficulty (double for "Easy")
    new_interval = current_interval * 2 if difficulty == 3 else review_intervals[difficulty]

    next_review = datetime.now() + timedelta(days=new_interval)

    cur.execute("""
        UPDATE flashcards 
        SET difficulty = ?, interval = ?, last_reviewed = CURRENT_TIMESTAMP, next_review = ?
        WHERE id = ?
    """, (difficulty, new_interval, next_review, flashcard_id))

    conn.commit()
    conn.close()


def update_progress(user_id, words_added=0, words_reviewed=0, correct_answers=0):
    """ Update user progress in the database. """
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
    UPDATE user_progress
    SET words_added = words_added + ?,
        words_reviewed = words_reviewed + ?,
        correct_answers = correct_answers + ?
    WHERE user_id = ?
    """, (words_added, words_reviewed, correct_answers, user_id))

    conn.commit()
    conn.close()


def track_new_word(user_id):
    """ Increase total words added count """
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO user_progress (user_id, words_added, words_reviewed, correct_answers) 
    VALUES (?, 0, 0, 0) 
    ON CONFLICT(user_id) 
    DO UPDATE SET words_added = words_added + 1
    """, (user_id,))

    conn.commit()
    conn.close()


def track_review(user_id, is_correct):
    """ Track user reviews without blocking multiple sessions per day """
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
        UPDATE flashcards 
        SET review_count = review_count + 1,
            correct_count = correct_count + ?,
            last_reviewed = CURRENT_TIMESTAMP
        WHERE user_id = ?
    """, (1 if is_correct else 0, user_id))

    # Update user progress
    cur.execute("""
            INSERT INTO user_progress (user_id, words_added, words_reviewed, correct_answers) 
            VALUES (?, 0, 1, ?) 
            ON CONFLICT(user_id) DO UPDATE 
            SET words_reviewed = words_reviewed + 1,
                correct_answers = correct_answers + ?
        """, (user_id, 1 if is_correct else 0, 1 if is_correct else 0))

    conn.commit()
    conn.close()


# Grammar Logic

def get_grammar_rules_by_level(level):
    """Retrieve all grammar rules for a specific level."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT id, title FROM grammar WHERE level = ?", (level,))
    rules = cursor.fetchall()

    conn.close()
    return rules


def get_grammar_rule(rule_id):
    """Retrieve a specific grammar rule by ID."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT title, explanation, examples FROM grammar WHERE id = ?", (rule_id,))
    rule = cursor.fetchone()

    conn.close()

    if rule:
        title, explanation, examples = rule
        return title, explanation, json.loads(examples)
    return None

grammar_rules = [
    ('Beginner', '이/가 형-아요/어요', 'Bu fe’l hozirgi zamonda qanday boʻlishini ifodalash uchun ishlatiladi. “형” sifatni bildiruvchi soʻz.', '날씨가 좋아요. / 기분이 나빠요.'),
    ('Beginner', '안 형', '“안” fe’l yoki sifatdan oldin kelib, inkor ma’nosini beradi.', '안 먹어요. / 안 바빠요.'),
    ('Beginner', '개/병/잔/그릇', 'Bu oʻlchov birliklari: “개” – dona, “병” – shisha, “잔” – piyola, “그릇” – kosa.', '물 한 병 주세요. / 사과 두 개 있어요.'),
    ('Beginner', '가격', 'Bu “narx” degan soʻzni bildiradi. Xarid qilinayotgan narsaning qiymatini soʻrashda ishlatiladi.', '이거 얼마예요? / 가격이 비싸요.'),
    ('Beginner', '에', '“-ga, -da” ma’nosini bildiradi. Joy yoki vaqtga ishora qilganda ishlatiladi.', '학교에 가요. / 아침에 일어나요.'),
]

def migrate():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    # Add the correct_streak column if it doesn't exist
    try:
        cur.executemany('''
INSERT INTO grammar (level, title, explanation, examples) 
                        VALUES
                        (?, ?, ?, ?)''', grammar_rules)
        print("Migration successful: Added 'correct_count' column.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print("Column 'correct_count' already exists. Skipping migration.")
        else:
            raise e

    conn.commit()
    cur.close()
    conn.close()

migrate()