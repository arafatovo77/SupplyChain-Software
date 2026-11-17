from flask import Flask, render_template, redirect, url_for, request, flash, send_file, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os

# ─── App Setup ───────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_DIR = os.path.join(BASE_DIR, "reports")
os.makedirs(REPORT_DIR, exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'scm_secret_2201_key')

db_url = os.environ.get('DATABASE_URL', f'sqlite:///{os.path.join(BASE_DIR, "supply_chain.db")}')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please login to access this page.'

REPORT_PASSWORD = "2201"

# ─── Models ───────────────────────────────────────────────────────────────────
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='member')  # admin, leader, member
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_leader(self):
        return self.role in ['admin', 'leader']


class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    members = db.relationship('User', backref='team', lazy=True, foreign_keys=[User.team_id])


class Buyer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    country = db.Column(db.String(100))
    contact_person = db.Column(db.String(150))
    email = db.Column(db.String(150))
    phone = db.Column(db.String(50))
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    styles = db.relationship('Style', backref='buyer', lazy=True)


class Style(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    style_no = db.Column(db.String(100), nullable=False)
    po = db.Column(db.String(100))
    description = db.Column(db.Text)
    buyer_id = db.Column(db.Integer, db.ForeignKey('buyer.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    season = db.Column(db.String(50))
    category = db.Column(db.String(100))
    fabric = db.Column(db.String(100))
    color = db.Column(db.String(100))
    quantity = db.Column(db.Integer, default=0)
    unit_price = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(50), default='Active')  # Active, Completed, On Hold, Cancelled
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    comments = db.relationship('StyleComment', backref='style', lazy=True, order_by='StyleComment.created_at.desc()')


class StyleComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    style_id = db.Column(db.Integer, db.ForeignKey('style.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    comment = db.Column(db.Text, nullable=False)
    comment_type = db.Column(db.String(50), default='General')  # General, Update, Issue, Resolution
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='comments')


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ─── Routes: Auth ─────────────────────────────────────────────────────────────
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password) and user.is_active:
            login_user(user, remember=True)
            flash(f'Welcome back, {user.full_name}!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# ─── Dashboard ────────────────────────────────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    total_buyers = Buyer.query.filter_by(is_active=True).count()
    total_styles = Style.query.count()
    total_teams = Team.query.count()
    total_users = User.query.filter_by(is_active=True).count()
    recent_styles = Style.query.order_by(Style.created_at.desc()).limit(5).all()
    status_counts = {}
    for s in ['Active', 'Completed', 'On Hold', 'Cancelled']:
        status_counts[s] = Style.query.filter_by(status=s).count()
    return render_template('dashboard.html',
        total_buyers=total_buyers, total_styles=total_styles,
        total_teams=total_teams, total_users=total_users,
        recent_styles=recent_styles, status_counts=status_counts)


# ─── Users ────────────────────────────────────────────────────────────────────
@app.route('/users')
@login_required
def users():
    if not current_user.is_admin:
        flash('Admin access required.', 'danger')
        return redirect(url_for('dashboard'))
    all_users = User.query.all()
    teams = Team.query.all()
    return render_template('users.html', users=all_users, teams=teams)


@app.route('/users/add', methods=['POST'])
@login_required
def add_user():
    if not current_user.is_admin:
        flash('Admin access required.', 'danger')
        return redirect(url_for('dashboard'))
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    full_name = request.form.get('full_name', '').strip()
    role = request.form.get('role', 'member')
    team_id = request.form.get('team_id') or None
    if User.query.filter_by(username=username).first():
        flash('Username already exists.', 'danger')
        return redirect(url_for('users'))
    user = User(username=username, full_name=full_name, role=role, team_id=team_id)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    flash(f'User "{full_name}" created successfully.', 'success')
    return redirect(url_for('users'))


@app.route('/users/toggle/<int:uid>')
@login_required
def toggle_user(uid):
    if not current_user.is_admin:
        flash('Admin access required.', 'danger')
        return redirect(url_for('dashboard'))
    user = User.query.get_or_404(uid)
    if user.role == 'admin':
        flash('Cannot deactivate admin.', 'danger')
        return redirect(url_for('users'))
    user.is_active = not user.is_active
    db.session.commit()
    flash(f'User {"activated" if user.is_active else "deactivated"}.', 'success')
    return redirect(url_for('users'))


@app.route('/users/reset_password/<int:uid>', methods=['POST'])
@login_required
def reset_password(uid):
    if not current_user.is_admin:
        flash('Admin access required.', 'danger')
        return redirect(url_for('dashboard'))
    user = User.query.get_or_404(uid)
    new_pass = request.form.get('new_password', '').strip()
    if not new_pass:
        flash('Password cannot be empty.', 'danger')
        return redirect(url_for('users'))
    user.set_password(new_pass)
    db.session.commit()
    flash(f'Password reset for {user.full_name}.', 'success')
    return redirect(url_for('users'))


# ─── Teams ────────────────────────────────────────────────────────────────────
@app.route('/teams')
@login_required
def teams():
    if not current_user.is_admin:
        flash('Admin access required.', 'danger')
        return redirect(url_for('dashboard'))
    all_teams = Team.query.all()
    return render_template('teams.html', teams=all_teams)


@app.route('/teams/add', methods=['POST'])
@login_required
def add_team():
    if not current_user.is_admin:
        flash('Admin access required.', 'danger')
        return redirect(url_for('dashboard'))
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    if Team.query.filter_by(name=name).first():
        flash('Team name already exists.', 'danger')
        return redirect(url_for('teams'))
    team = Team(name=name, description=description)
    db.session.add(team)
    db.session.commit()
    flash(f'Team "{name}" created.', 'success')
    return redirect(url_for('teams'))


@app.route('/teams/delete/<int:tid>')
@login_required
def delete_team(tid):
    if not current_user.is_admin:
        flash('Admin access required.', 'danger')
        return redirect(url_for('dashboard'))
    team = Team.query.get_or_404(tid)
    db.session.delete(team)
    db.session.commit()
    flash('Team deleted.', 'success')
    return redirect(url_for('teams'))


# ─── Buyers ───────────────────────────────────────────────────────────────────
@app.route('/buyers')
@login_required
def buyers():
    all_buyers = Buyer.query.filter_by(is_active=True).order_by(Buyer.name).all()
    return render_template('buyers.html', buyers=all_buyers)


@app.route('/buyers/add', methods=['POST'])
@login_required
def add_buyer():
    if not current_user.is_leader:
        flash('Team Leader or Admin access required.', 'danger')
        return redirect(url_for('buyers'))
    name = request.form.get('name', '').strip()
    country = request.form.get('country', '').strip()
    contact_person = request.form.get('contact_person', '').strip()
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()
    notes = request.form.get('notes', '').strip()
    if Buyer.query.filter_by(name=name).first():
        flash('Buyer already exists.', 'danger')
        return redirect(url_for('buyers'))
    buyer = Buyer(name=name, country=country, contact_person=contact_person,
                  email=email, phone=phone, notes=notes)
    db.session.add(buyer)
    db.session.commit()
    flash(f'Buyer "{name}" added.', 'success')
    return redirect(url_for('buyers'))


@app.route('/buyers/edit/<int:bid>', methods=['POST'])
@login_required
def edit_buyer(bid):
    if not current_user.is_leader:
        flash('Team Leader or Admin access required.', 'danger')
        return redirect(url_for('buyers'))
    buyer = Buyer.query.get_or_404(bid)
    buyer.name = request.form.get('name', buyer.name).strip()
    buyer.country = request.form.get('country', '').strip()
    buyer.contact_person = request.form.get('contact_person', '').strip()
    buyer.email = request.form.get('email', '').strip()
    buyer.phone = request.form.get('phone', '').strip()
    buyer.notes = request.form.get('notes', '').strip()
    db.session.commit()
    flash('Buyer updated.', 'success')
    return redirect(url_for('buyers'))


# ─── Styles ───────────────────────────────────────────────────────────────────
@app.route('/styles')
@login_required
def styles():
    buyer_id = request.args.get('buyer_id', type=int)
    team_id = request.args.get('team_id', type=int)
    status = request.args.get('status', '')
    q = request.args.get('q', '').strip()

    query = Style.query
    if buyer_id:
        query = query.filter_by(buyer_id=buyer_id)
    if team_id:
        query = query.filter_by(team_id=team_id)
    if status:
        query = query.filter_by(status=status)
    if q:
        query = query.filter(Style.style_no.ilike(f'%{q}%') | Style.description.ilike(f'%{q}%') | Style.po.ilike(f'%{q}%'))

    all_styles = query.order_by(Style.created_at.desc()).all()
    all_buyers = Buyer.query.filter_by(is_active=True).order_by(Buyer.name).all()
    all_teams = Team.query.all()
    return render_template('styles.html', styles=all_styles, buyers=all_buyers,
                           teams=all_teams, selected_buyer=buyer_id,
                           selected_team=team_id, selected_status=status, search_q=q)


@app.route('/styles/add', methods=['POST'])
@login_required
def add_style():
    style_no = request.form.get('style_no', '').strip()
    po = request.form.get('po', '').strip()
    description = request.form.get('description', '').strip()
    buyer_id = request.form.get('buyer_id', type=int)
    team_id = request.form.get('team_id') or None
    season = request.form.get('season', '').strip()
    category = request.form.get('category', '').strip()
    fabric = request.form.get('fabric', '').strip()
    color = request.form.get('color', '').strip()
    quantity = request.form.get('quantity', 0, type=int)
    unit_price = request.form.get('unit_price', 0.0, type=float)
    status = request.form.get('status', 'Active')
    initial_comment = request.form.get('initial_comment', '').strip()

    style = Style(style_no=style_no, po=po, description=description, buyer_id=buyer_id,
                  team_id=team_id, season=season, category=category, fabric=fabric,
                  color=color, quantity=quantity, unit_price=unit_price, status=status,
                  created_by=current_user.id)
    db.session.add(style)
    db.session.flush()

    if initial_comment:
        comment = StyleComment(style_id=style.id, user_id=current_user.id,
                               comment=initial_comment, comment_type='General')
        db.session.add(comment)

    db.session.commit()
    flash(f'Style "{style_no}" added successfully.', 'success')
    return redirect(url_for('styles'))


# ─── Excel Import (Styles) ────────────────────────────────────────────────────
IMPORT_HEADERS = {
    'styleno': 'style_no',
    'style': 'style_no',
    'styleref': 'style_no',
    'stylenumber': 'style_no',
    'po': 'po',
    'pono': 'po',
    'purchaseorder': 'po',
    'jobno': 'po',
    'description': 'description',
    'desc': 'description',
    'styledescription': 'description',
    'item': 'description',
    'itemname': 'description',
    'gmtsitem': 'description',
    'product': 'description',
    'buyer': 'buyer',
    'buyername': 'buyer',
    'customer': 'buyer',
    'team': 'team',
    'teamname': 'team',
    'season': 'season',
    'category': 'category',
    'cat': 'category',
    'garmentcategory': 'category',
    'fabric': 'fabric',
    'fabrictype': 'fabric',
    'color': 'color',
    'colour': 'color',
    'colorwash': 'color',
    'quantity': 'quantity',
    'qty': 'quantity',
    'orderqty': 'quantity',
    'orderquantity': 'quantity',
    'unitprice': 'unit_price',
    'price': 'unit_price',
    'fob': 'unit_price',
    'fobprice': 'unit_price',
    'rate': 'unit_price',
    'unitfobprice': 'unit_price',
    'status': 'status',
    'remark': 'remark',
    'remarks': 'remark',
    'comment': 'remark',
    'comments': 'remark',
    'note': 'remark',
    'notes': 'remark',
    'followup': 'remark',
}

VALID_STATUSES = {'Active', 'Completed', 'On Hold', 'Cancelled'}


def _norm_header(value):
    if value is None:
        return ''
    s = str(value).strip().lower()
    for ch in (' ', '_', '-', '.', '/', '\\'):
        s = s.replace(ch, '')
    return s


def _to_int(value):
    try:
        if value is None or str(value).strip() == '':
            return None
        return int(float(str(value).replace(',', '').strip()))
    except (ValueError, TypeError):
        return None


def _to_float(value):
    try:
        if value is None or str(value).strip() == '':
            return None
        return float(str(value).replace(',', '').replace('$', '').strip())
    except (ValueError, TypeError):
        return None


def _get_or_create_buyer(name):
    name = str(name).strip()
    buyer = Buyer.query.filter(db.func.lower(Buyer.name) == name.lower()).first()
    if not buyer:
        buyer = Buyer(name=name, is_active=True)
        db.session.add(buyer)
        db.session.flush()
    return buyer


def _get_or_create_team(name):
    name = str(name).strip()
    team = Team.query.filter(db.func.lower(Team.name) == name.lower()).first()
    if not team:
        team = Team(name=name)
        db.session.add(team)
        db.session.flush()
    return team


def _import_styles_workbook(wb, user_id):
    """Parse the active sheet and upsert styles. Returns (added, updated, skipped, remarks_added)."""
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return 0, 0, [('—', 'Empty file — no rows found.')], 0

    # Find the header row (scan first 3 rows)
    header_idx = None
    colmap = {}
    for i in range(min(3, len(rows))):
        mapping = {}
        for j, cell in enumerate(rows[i]):
            field = IMPORT_HEADERS.get(_norm_header(cell))
            if field and field not in mapping:
                mapping[field] = j
        if 'style_no' in mapping or len(mapping) >= 2:
            header_idx = i
            colmap = mapping
            break
    if header_idx is None or 'style_no' not in colmap:
        return 0, 0, [('—', 'No heading row found. The file needs a heading row with at least a "Style No" column (e.g. Style No, Buyer, Quantity, Unit Price).')], 0

    added = 0
    updated = 0
    remarks_added = 0
    skipped = []
    for r in range(header_idx + 1, len(rows)):
        row = rows[r]
        excel_row = r + 1

        def val(field):
            j = colmap.get(field)
            if j is None or j >= len(row):
                return None
            v = row[j]
            if isinstance(v, str):
                v = v.strip()
                return v if v else None
            return v

        style_no = val('style_no')
        if style_no is None:
            continue  # blank row — ignore silently
        style_no = str(style_no).strip()

        buyer_name = val('buyer')
        if not buyer_name:
            skipped.append((excel_row, 'Style ' + style_no + ': no Buyer — row skipped.'))
            continue
        buyer = _get_or_create_buyer(buyer_name)

        po = val('po')
        po = str(po).strip() if po is not None else ''
        style = Style.query.filter_by(style_no=style_no, buyer_id=buyer.id, po=po).first()
        if style is None:
            if po:
                # A PO-less copy exists (imported before PO) — adopt it, don't duplicate
                style = Style.query.filter_by(style_no=style_no, buyer_id=buyer.id, po='').first()
            else:
                # Blank-PO row: update the most recent copy under this Style No + Buyer
                style = Style.query.filter_by(style_no=style_no, buyer_id=buyer.id).order_by(Style.updated_at.desc()).first()
        is_new = style is None
        if is_new:
            style = Style(style_no=style_no, buyer_id=buyer.id, po=po, created_by=user_id)
            db.session.add(style)
        elif po:
            style.po = po

        # Only overwrite a field when the cell has a value (blank keeps old value)
        if val('description') is not None:
            style.description = str(val('description'))
        if val('team') is not None:
            style.team_id = _get_or_create_team(val('team')).id
        if val('season') is not None:
            style.season = str(val('season'))
        if val('category') is not None:
            style.category = str(val('category'))
        if val('fabric') is not None:
            style.fabric = str(val('fabric'))
        if val('color') is not None:
            style.color = str(val('color'))
        qty = _to_int(val('quantity'))
        if qty is not None:
            style.quantity = qty
        price = _to_float(val('unit_price'))
        if price is not None:
            style.unit_price = price
        status = val('status')
        if status is not None:
            status = str(status).strip().title()
            if status in VALID_STATUSES:
                style.status = status
            elif is_new:
                style.status = 'Active'
        if is_new and not style.status:
            style.status = 'Active'

        db.session.flush()

        remark = val('remark')
        if remark is not None:
            remark = str(remark).strip()
            latest = style.comments[0].comment if style.comments else None
            if remark and remark != latest:
                db.session.add(StyleComment(style_id=style.id, user_id=user_id,
                                            comment=remark, comment_type='General'))
                remarks_added += 1

        if is_new:
            added += 1
        else:
            updated += 1

    db.session.commit()
    return added, updated, skipped, remarks_added


@app.route('/styles/import', methods=['GET', 'POST'])
@login_required
def import_styles():
    result = None
    if request.method == 'POST':
        f = request.files.get('file')
        if not f or not f.filename:
            flash('Please choose an Excel (.xlsx) file first.', 'danger')
            return redirect(url_for('import_styles'))
        if not f.filename.lower().endswith('.xlsx'):
            flash('Only .xlsx Excel files are supported.', 'danger')
            return redirect(url_for('import_styles'))
        try:
            import openpyxl
            wb = openpyxl.load_workbook(f, data_only=True)
            added, updated, skipped, remarks_added = _import_styles_workbook(wb, current_user.id)
        except Exception as e:
            flash('Could not read this file: ' + str(e), 'danger')
            return redirect(url_for('import_styles'))
        result = {'added': added, 'updated': updated, 'skipped': skipped,
                  'remarks_added': remarks_added,
                  'filename': f.filename}
        flash('Import finished: ' + str(added) + ' added, ' + str(updated) + ' updated, ' + str(len(skipped)) + ' skipped.', 'success' if not skipped else 'warning')
    return render_template('import_styles.html', result=result)


@app.route('/styles/<int:sid>')
@login_required
def style_detail(sid):
    style = Style.query.get_or_404(sid)
    all_buyers = Buyer.query.filter_by(is_active=True).order_by(Buyer.name).all()
    all_teams = Team.query.all()
    return render_template('style_detail.html', style=style, buyers=all_buyers, teams=all_teams)


@app.route('/styles/<int:sid>/edit', methods=['POST'])
@login_required
def edit_style(sid):
    style = Style.query.get_or_404(sid)
    style.style_no = request.form.get('style_no', style.style_no).strip()
    style.po = request.form.get('po', style.po or '').strip()
    style.description = request.form.get('description', '').strip()
    style.buyer_id = request.form.get('buyer_id', type=int)
    style.team_id = request.form.get('team_id') or None
    style.season = request.form.get('season', '').strip()
    style.category = request.form.get('category', '').strip()
    style.fabric = request.form.get('fabric', '').strip()
    style.color = request.form.get('color', '').strip()
    style.quantity = request.form.get('quantity', 0, type=int)
    style.unit_price = request.form.get('unit_price', 0.0, type=float)
    style.status = request.form.get('status', 'Active')
    style.updated_at = datetime.utcnow()
    db.session.commit()
    flash('Style updated.', 'success')
    return redirect(url_for('style_detail', sid=sid))


@app.route('/styles/<int:sid>/comment', methods=['POST'])
@login_required
def add_comment(sid):
    style = Style.query.get_or_404(sid)
    comment_text = request.form.get('comment', '').strip()
    comment_type = request.form.get('comment_type', 'General')
    if not comment_text:
        flash('Comment cannot be empty.', 'danger')
        return redirect(url_for('style_detail', sid=sid))
    comment = StyleComment(style_id=sid, user_id=current_user.id,
                           comment=comment_text, comment_type=comment_type)
    db.session.add(comment)
    db.session.commit()
    flash('Comment added.', 'success')
    return redirect(url_for('style_detail', sid=sid))


# ─── Reports ──────────────────────────────────────────────────────────────────
@app.route('/reports')
@login_required
def reports():
    buyers = Buyer.query.filter_by(is_active=True).order_by(Buyer.name).all()
    teams = Team.query.all()
    report_files = []
    if os.path.exists(REPORT_DIR):
        for f in os.listdir(REPORT_DIR):
            fp = os.path.join(REPORT_DIR, f)
            report_files.append({
                'name': f,
                'size': round(os.path.getsize(fp) / 1024, 1),
                'modified': datetime.fromtimestamp(os.path.getmtime(fp)).strftime('%Y-%m-%d %H:%M')
            })
    report_files.sort(key=lambda x: x['modified'], reverse=True)
    return render_template('reports.html', buyers=buyers, teams=teams, report_files=report_files)


@app.route('/reports/generate', methods=['POST'])
@login_required
def generate_report():
    report_type = request.form.get('report_type', 'excel')
    buyer_id = request.form.get('buyer_id', type=int)
    team_id = request.form.get('team_id', type=int)
    status = request.form.get('status', '')
    include_comments = request.form.get('include_comments') == 'on'

    query = Style.query
    if buyer_id:
        query = query.filter_by(buyer_id=buyer_id)
    if team_id:
        query = query.filter_by(team_id=team_id)
    if status:
        query = query.filter_by(status=status)
    styles_data = query.order_by(Style.buyer_id, Style.style_no).all()

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    if report_type == 'excel':
        filename = f'SCM_Report_{timestamp}.xlsx'
        filepath = os.path.join(REPORT_DIR, filename)
        _generate_excel(styles_data, filepath, include_comments)
        flash(f'Excel report generated: {filename}', 'success')
    else:
        filename = f'SCM_Report_{timestamp}.pdf'
        filepath = os.path.join(REPORT_DIR, filename)
        _generate_pdf(styles_data, filepath, include_comments)
        flash(f'PDF report generated: {filename}', 'success')

    return redirect(url_for('reports'))


@app.route('/reports/download/<filename>', methods=['GET', 'POST'])
@login_required
def download_report(filename):
    if request.method == 'POST':
        entered = request.form.get('password', '').strip()
        if entered != REPORT_PASSWORD:
            flash('Wrong report password!', 'danger')
            return redirect(url_for('reports'))
        filepath = os.path.join(REPORT_DIR, filename)
        if not os.path.exists(filepath):
            flash('File not found.', 'danger')
            return redirect(url_for('reports'))
        return send_file(filepath, as_attachment=True)
    return render_template('report_password.html', filename=filename)


@app.route('/reports/delete/<filename>')
@login_required
def delete_report(filename):
    if not current_user.is_admin:
        flash('Admin access required.', 'danger')
        return redirect(url_for('reports'))
    filepath = os.path.join(REPORT_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
        flash(f'Report "{filename}" deleted.', 'success')
    return redirect(url_for('reports'))


# ─── Report Generators ────────────────────────────────────────────────────────
def _generate_excel(styles_data, filepath, include_comments=False):
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Style Report"

    # Header
    header_fill = PatternFill("solid", fgColor="1a3c5e")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    thin = Side(style='thin', color='CCCCCC')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    headers = ['#', 'Style No', 'Description', 'Buyer', 'Team', 'Season',
               'Category', 'Fabric', 'Color', 'Quantity', 'Unit Price ($)',
               'Total Value ($)', 'Status', 'Created At']
    if include_comments:
        headers.append('Latest Comment')

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = border

    ws.row_dimensions[1].height = 25

    alt_fill = PatternFill("solid", fgColor="EBF3FB")
    for row_idx, style in enumerate(styles_data, 2):
        fill = alt_fill if row_idx % 2 == 0 else PatternFill()
        total_val = (style.quantity or 0) * (style.unit_price or 0)
        latest_comment = ''
        if include_comments and style.comments:
            latest_comment = style.comments[0].comment[:200]
        row_data = [
            row_idx - 1, style.style_no, style.description or '',
            style.buyer.name if style.buyer else '',
            style.team.name if style.team else '',
            style.season or '', style.category or '', style.fabric or '',
            style.color or '', style.quantity or 0, style.unit_price or 0,
            round(total_val, 2), style.status,
            style.created_at.strftime('%Y-%m-%d')
        ]
        if include_comments:
            row_data.append(latest_comment)
        for col, val in enumerate(row_data, 1):
            cell = ws.cell(row=row_idx, column=col, value=val)
            cell.fill = fill
            cell.border = border
            cell.alignment = Alignment(vertical='center', wrap_text=True)

    # Auto-width
    for col in range(1, len(headers) + 1):
        max_len = 0
        for row in ws.iter_rows(min_col=col, max_col=col):
            for cell in row:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[get_column_letter(col)].width = min(max(max_len + 2, 10), 40)

    # Summary sheet
    ws2 = wb.create_sheet("Summary")
    ws2['A1'] = 'Supply Chain Management - Summary Report'
    ws2['A1'].font = Font(bold=True, size=14, color="1a3c5e")
    ws2['A3'] = 'Generated:'
    ws2['B3'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    ws2['A4'] = 'Total Styles:'
    ws2['B4'] = len(styles_data)
    total_qty = sum(s.quantity or 0 for s in styles_data)
    total_val = sum((s.quantity or 0) * (s.unit_price or 0) for s in styles_data)
    ws2['A5'] = 'Total Quantity:'
    ws2['B5'] = total_qty
    ws2['A6'] = 'Total Value ($):'
    ws2['B6'] = round(total_val, 2)

    wb.save(filepath)


def _generate_pdf(styles_data, filepath, include_comments=False):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    doc = SimpleDocTemplate(filepath, pagesize=landscape(A4),
                            leftMargin=1*cm, rightMargin=1*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle('Title', parent=styles['Title'],
                                  fontSize=16, textColor=colors.HexColor('#1a3c5e'),
                                  spaceAfter=6)
    elements.append(Paragraph('Supply Chain Management Report', title_style))
    elements.append(Paragraph(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
                               styles['Normal']))
    elements.append(Spacer(1, 0.5*cm))

    headers = ['#', 'Style No', 'Buyer', 'Season', 'Category', 'Qty', 'Price ($)', 'Status']
    if include_comments:
        headers.append('Comment')

    table_data = [headers]
    for idx, style in enumerate(styles_data, 1):
        row = [
            str(idx), style.style_no,
            style.buyer.name if style.buyer else '',
            style.season or '', style.category or '',
            str(style.quantity or 0), f'{style.unit_price or 0:.2f}',
            style.status
        ]
        if include_comments and style.comments:
            row.append(style.comments[0].comment[:80] + ('...' if len(style.comments[0].comment) > 80 else ''))
        elif include_comments:
            row.append('')
        table_data.append(row)

    col_widths = [1*cm, 3*cm, 4*cm, 2.5*cm, 3*cm, 1.5*cm, 2*cm, 2.5*cm]
    if include_comments:
        col_widths.append(5*cm)

    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a3c5e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#EBF3FB')]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ROWHEIGHT', (0, 0), (-1, -1), 18),
    ]))
    elements.append(table)

    # Summary
    elements.append(Spacer(1, 0.5*cm))
    total_qty = sum(s.quantity or 0 for s in styles_data)
    total_val = sum((s.quantity or 0) * (s.unit_price or 0) for s in styles_data)
    elements.append(Paragraph(f'<b>Total Styles:</b> {len(styles_data)} | <b>Total Qty:</b> {total_qty} | <b>Total Value:</b> ${total_val:,.2f}',
                               styles['Normal']))
    doc.build(elements)


# ─── Init DB & Run ────────────────────────────────────────────────────────────
def init_db():
    with app.app_context():
        db.create_all()
        # Lightweight migration: add the PO column on existing installs
        try:
            from sqlalchemy import inspect as _sa_inspect, text as _sa_text
            _cols = [c['name'] for c in _sa_inspect(db.engine).get_columns('style')]
            if 'po' not in _cols:
                with db.engine.begin() as _conn:
                    _conn.execute(_sa_text('ALTER TABLE style ADD COLUMN po VARCHAR(100)'))
                    _conn.execute(_sa_text("UPDATE style SET po = '' WHERE po IS NULL"))
        except Exception as _e:
            print(f"Warning during PO migration: {_e}")
        # Create default admin if not exists
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', full_name='Administrator (Boss)', role='admin', is_active=True)
            admin.set_password('admin2201')
            db.session.add(admin)
            db.session.commit()
            print("✅ Default admin created: username=admin, password=admin2201")

# Auto-initialize database on startup
try:
    init_db()
except Exception as e:
    print(f"Warning during DB init: {e}")

if __name__ == '__main__':
    print("🚀 Supply Chain Management System starting...")
    print("📌 Open: http://127.0.0.1:5000")
    print("👤 Default Login: admin / admin2201")
    app.run(debug=True, host='0.0.0.0', port=5000)
