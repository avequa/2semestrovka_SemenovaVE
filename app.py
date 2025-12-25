from flask import Flask, session, redirect, render_template, url_for, request
from db import get_connection
import datetime

app = Flask(__name__)
app.secret_key = 'very-secret-key'

@app.route('/')
def index():
    if session.get('user_id'):
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            return render_template('users/register.html', error='Введите логин и пароль')

        conn = get_connection()
        cur = conn.cursor()
        cur.execute('SELECT id FROM users WHERE username = %s', (username,))
        if cur.fetchone():
            cur.close()
            conn.close()
            return render_template('users/register.html', error='Пользователь с таким паролем уже существует')

        cur.execute("INSERT INTO users (username, password) VALUES (%s, %s) RETURNING id", (username, password))
        user_id = cur.fetchone()[0]
        cur.execute("INSERT INTO developer_profiles (user_id, joined_at) VALUES (%s, CURRENT_DATE)", (user_id,))
        conn.commit()
        cur.close()
        conn.close()
        session['user_id'] = user_id
        return redirect(url_for('dashboard'))

    return render_template('users/register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            return render_template('users/login.html', error='Введите логин и пароль')

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, password FROM users WHERE username = %s", (username,))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row or row[1] != password:
            return render_template('users/login.html', error='Неверные данные')

        session['user_id'] = row[0]
        return redirect(url_for('dashboard'))

    return render_template('users/login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT u.username, p.joined_at FROM users u JOIN developer_profiles p ON u.id=p.user_id WHERE u.id=%s", (user_id,))
    row = cur.fetchone()

    cur.execute("SELECT id, name FROM projects WHERE user_id=%s ORDER BY id", (user_id,))
    projects = [{'id': i[0], 'name': i[1]} for i in cur.fetchall()]

    cur.execute("""
        SELECT i.title, i.is_closed, i.due_date, p.name, i.id, i.closed_at 
        FROM issues i 
        JOIN projects p ON i.project_id = p.id 
        WHERE p.user_id = %s 
        ORDER BY i.due_date ASC
    """, (user_id,))

    issues = cur.fetchall()

    total = len(issues)
    closed = 0
    overdue = 0
    today = datetime.date.today()

    for title, is_closed, due_date, project_name, task_id, closed_at in issues:
        if is_closed:
            closed += 1
        elif due_date and due_date < today:
            overdue += 1

    progress = int((closed / total) * 100) if total else 0

    if total == 0:
        if projects:
            forecast = {'level': 'none', 'title': 'Проекты есть', 'text': 'Добавьте задачи в проекты'}
        else:
            forecast = {'level': 'none', 'title': 'Нет проектов', 'text': 'Создайте проект и добавьте задачи'}
    elif progress >= 80 and overdue == 0:
        forecast = {'level': 'good', 'title': 'Проекты под контролем', 'text': 'Отличная скорость разработки'}
    elif progress >= 50 or overdue > 3:
        forecast = {'level': 'warning', 'title': 'Есть проблемы', 'text': 'Некоторые задачи требуют внимания'}
    else:
        forecast = {'level': 'danger', 'title': 'Критическое отставание ;)', 'text': 'Вам не повезло'}

    cur.close()
    conn.close()

    return render_template('profiles/dashboard.html',
                           username=row[0],
                           joined_at=row[1],
                           forecast=forecast,
                           precent_of_success=progress,
                           projects=projects,
                           issues=issues,
                           today=today)


@app.route('/projects')
def projects():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT p.id, p.name, 
               ARRAY_AGG(t.name) as tags
        FROM projects p
        LEFT JOIN project_tags pt ON p.id = pt.project_id
        LEFT JOIN tags t ON pt.tag_id = t.id
        WHERE p.user_id = %s
        GROUP BY p.id, p.name
        ORDER BY p.id
    """, (user_id,))

    projects = []
    for proj_id, name, tags in cur.fetchall():
        projects.append({
            'id': proj_id,
            'name': name,
            'tags': [tag for tag in (tags or []) if tag]})

    cur.close()
    conn.close()
    return render_template('projects/list.html', projects=projects)


@app.route('/projects/add', methods=['GET', 'POST'])
def add_project():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        tags_input = request.form.get('tags', '').strip()

        if not name:
            return render_template('projects/add.html', error='Введите название проекта')

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("INSERT INTO projects (user_id, name) VALUES (%s, %s) RETURNING id", (user_id, name))
        project_id = cur.fetchone()[0]

        if tags_input:
            tags = [tag.strip().lower() for tag in tags_input.split(',') if tag.strip()]
            for tag_name in tags:
                cur.execute("INSERT INTO tags (name) VALUES (%s) ON CONFLICT (name) DO NOTHING RETURNING id",
                            (tag_name,))
                tag_row = cur.fetchone()
                if tag_row:
                    tag_id = tag_row[0]
                else:
                    cur.execute("SELECT id FROM tags WHERE name = %s", (tag_name,))
                    tag_id = cur.fetchone()[0]

                # Связываем тег с проектом
                cur.execute("INSERT INTO project_tags (project_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                            (project_id, tag_id))

        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for('projects'))

    return render_template('projects/add.html')


@app.route('/project/<int:project_id>/delete', methods=['POST'])
def delete_project(project_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT id FROM projects WHERE id=%s AND user_id=%s", (project_id, user_id))
    if not cur.fetchone():
        cur.close()
        conn.close()
        return redirect(url_for('projects'))

    cur.execute("DELETE FROM issues WHERE project_id=%s", (project_id,))
    cur.execute("DELETE FROM project_tags WHERE project_id=%s", (project_id,))
    cur.execute("DELETE FROM projects WHERE id=%s", (project_id,))

    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for('projects'))

@app.route('/tasks/add/<int:project_id>', methods=['GET', 'POST'])
def add_task(project_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        due_date = request.form.get('due_date')
        if not title or not due_date:
            return render_template('tasks/add.html', project_id=project_id, error='Введите название и дату')
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO issues (project_id, title, due_date) VALUES (%s, %s, %s)", (project_id, title, due_date))
        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for('dashboard'))

    return render_template('tasks/add.html', project_id=project_id)

@app.route('/project/<int:project_id>')
def project_detail(project_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT name FROM projects WHERE id=%s AND user_id=%s", (project_id, user_id))
    project = cur.fetchone()

    if not project:
        cur.close()
        conn.close()
        return redirect(url_for('projects'))

    cur.execute("""
        SELECT id, title, due_date, is_closed, closed_at 
        FROM issues 
        WHERE project_id=%s 
        ORDER BY is_closed, due_date ASC
    """, (project_id,))

    issues = []
    today = datetime.date.today()

    for task_id, title, due_date, is_closed, closed_at in cur.fetchall():
        days_left = (due_date - today).days if due_date else None
        issues.append({
            'id': task_id,
            'title': title,
            'due_date': due_date,
            'is_closed': is_closed,
            'closed_at': closed_at,
            'days_left': days_left
        })

    cur.close()
    conn.close()

    return render_template('projects/detail.html', project={'id': project_id, 'name': project[0]}, issues=issues)

@app.route('/task/<int:task_id>/close')
def close_task(task_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE issues 
        SET is_closed = TRUE, closed_at = CURRENT_DATE 
        WHERE id = %s AND project_id IN (
            SELECT id FROM projects WHERE user_id = %s
        )
    """, (task_id, user_id))

    conn.commit()
    cur.close()
    conn.close()

    return redirect(request.referrer or url_for('dashboard'))

@app.route('/task/<int:task_id>/reopen')
def reopen_task(task_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE issues 
        SET is_closed = FALSE, closed_at = NULL 
        WHERE id = %s AND project_id IN (
            SELECT id FROM projects WHERE user_id = %s
        )
    """, (task_id, user_id))

    conn.commit()
    cur.close()
    conn.close()

    return redirect(request.referrer or url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True)
