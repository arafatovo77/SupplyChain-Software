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
# Team <-> Buyer: which buyers a team works on
team_buyers = db.Table('team_buyers',
    db.Column('team_id', db.Integer, db.ForeignKey('team.id'), primary_key=True),
    db.Column('buyer_id', db.Integer, db.ForeignKey('buyer.id'), primary_key=True))
# User <-> Buyer: which buyers a member is allocated (follows)
user_buyers = db.Table('user_buyers',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('buyer_id', db.Integer, db.ForeignKey('buyer.id'), primary_key=True))


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='member')  # admin, leader, member
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Buyers this member is allocated (follows). Empty = falls back to the whole team.
    buyers = db.relationship('Buyer', secondary=user_buyers, backref='followers', lazy=True)

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
    leader_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    members = db.relationship('User', backref='team', lazy=True, foreign_keys=[User.team_id])
    leader = db.relationship('User', foreign_keys=[leader_id])
    # Buyers this team works on (leader sees all of these)
    buyers = db.relationship('Buyer', secondary=team_buyers, backref='teams', lazy=True)


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
    buyer_id = db.Column(db.Integer, db.ForeignKey('buyer.id'), nullable=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    team = db.relationship('Team', backref='styles', lazy=True)
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


def visible_buyer_ids(user):
    """Buyer ids this user may see, or None for 'all' (admin).

    Leader: all buyers of teams they lead.
    Member: their allocated buyers; if none allocated yet, their whole team's buyers.
    """
    if user is None:
        return set()
    if user.is_admin:
        return None
    ids = set()
    for tm in Team.query.filter_by(leader_id=user.id).all():
        ids.update(b.id for b in tm.buyers)
    if user.buyers:
        ids.update(b.id for b in user.buyers)
    elif user.team_id:
        team = Team.query.get(user.team_id)
        if team:
            ids.update(b.id for b in team.buyers)
    return ids


def visible_styles_query(query, user):
    """Restrict a Style query to what the user may see.

    Admin sees everything. Others see styles whose buyer is visible to them,
    plus buyer-less (Style-Name-only) placeholders they created themselves.
    """
    if user is None:
        return query.filter(db.false())
    if user.is_admin:
        return query
    vids = visible_buyer_ids(user)
    return query.filter(
        (Style.buyer_id.in_(vids)) |
        ((Style.buyer_id.is_(None)) & (Style.created_by == user.id))
    )


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
    vids = visible_buyer_ids(current_user)
    if vids is None:
        total_buyers = Buyer.query.filter_by(is_active=True).count()
        style_q = Style.query
    else:
        total_buyers = Buyer.query.filter_by(is_active=True).filter(Buyer.id.in_(vids)).count()
        style_q = visible_styles_query(Style.query, current_user)
    total_styles = style_q.count()
    total_teams = Team.query.count()
    total_users = User.query.filter_by(is_active=True).count()
    recent_styles = style_q.order_by(Style.created_at.desc()).limit(5).all()
    status_counts = {}
    for s in ['Active', 'Completed', 'On Hold', 'Cancelled']:
        status_counts[s] = style_q.filter_by(status=s).count()
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
    all_users = User.query.filter_by(is_active=True).order_by(User.full_name).all()
    all_buyers = Buyer.query.filter_by(is_active=True).order_by(Buyer.name).all()
    return render_template('teams.html', teams=all_teams, users=all_users, buyers=all_buyers)


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
    leader_id = request.form.get('leader_id', type=int)
    if leader_id:
        team.leader_id = leader_id
    db.session.add(team)
    db.session.flush()
    # Members: set their team
    for uid in request.form.getlist('member_ids'):
        u = User.query.get(int(uid))
        if u:
            u.team_id = team.id
    # Buyers: the team's buyers
    for bid in request.form.getlist('buyer_ids'):
        b = Buyer.query.get(int(bid))
        if b:
            team.buyers.append(b)
    db.session.commit()
    flash(f'Team "{name}" created.', 'success')
    return redirect(url_for('team_detail', tid=team.id))


@app.route('/teams/<int:tid>')
@login_required
def team_detail(tid):
    if not current_user.is_admin:
        flash('Admin access required.', 'danger')
        return redirect(url_for('dashboard'))
    team = Team.query.get_or_404(tid)
    all_users = User.query.filter_by(is_active=True).order_by(User.full_name).all()
    all_buyers = Buyer.query.filter_by(is_active=True).order_by(Buyer.name).all()
    return render_template('team_detail.html', team=team, users=all_users, buyers=all_buyers)


@app.route('/teams/<int:tid>/update', methods=['POST'])
@login_required
def update_team(tid):
    if not current_user.is_admin:
        flash('Admin access required.', 'danger')
        return redirect(url_for('dashboard'))
    team = Team.query.get_or_404(tid)
    team.name = request.form.get('name', team.name).strip()
    team.description = request.form.get('description', '').strip()
    team.leader_id = request.form.get('leader_id', type=int)
    # Members: users ticked belong to this team; unticked members of this team leave it
    chosen = {int(x) for x in request.form.getlist('member_ids')}
    for u in User.query.filter_by(team_id=team.id).all():
        if u.id not in chosen:
            u.team_id = None
            # Leaving the team also clears their buyer allocation for this team's buyers
            u.buyers = [b for b in u.buyers if b not in team.buyers]
    for uid in chosen:
        u = User.query.get(uid)
        if u:
            u.team_id = team.id
    # Team buyers
    team.buyers = [Buyer.query.get(int(bid)) for bid in request.form.getlist('buyer_ids')]
    team.buyers = [b for b in team.buyers if b is not None]
    # Drop allocations to buyers no longer in the team
    for u in User.query.filter_by(team_id=team.id).all():
        u.buyers = [b for b in u.buyers if b in team.buyers]
    db.session.commit()
    flash(f'Team "{team.name}" updated.', 'success')
    return redirect(url_for('team_detail', tid=tid))


@app.route('/teams/<int:tid>/allocate', methods=['POST'])
@login_required
def allocate_buyers(tid):
    if not current_user.is_admin:
        flash('Admin access required.', 'danger')
        return redirect(url_for('dashboard'))
    team = Team.query.get_or_404(tid)
    # For each member, the ticked buyers (within this team's buyers) are their allocation.
    # An empty selection = no allocation (member then sees the whole team, per the fallback).
    for u in User.query.filter_by(team_id=team.id).all():
        chosen = {int(x) for x in request.form.getlist(f'alloc_{u.id}')}
        u.buyers = [b for b in team.buyers if b.id in chosen]
    db.session.commit()
    flash('Buyer allocation saved.', 'success')
    return redirect(url_for('team_detail', tid=tid))


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
    vids = visible_buyer_ids(current_user)
    q = Buyer.query.filter_by(is_active=True)
    if vids is not None:
        q = q.filter(Buyer.id.in_(vids))
    all_buyers = q.order_by(Buyer.name).all()
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
    po = request.args.get('po', '').strip()
    q = request.args.get('q', '').strip()

    query = visible_styles_query(Style.query, current_user)
    if buyer_id:
        query = query.filter_by(buyer_id=buyer_id)
    if team_id:
        query = query.filter_by(team_id=team_id)
    if status:
        query = query.filter_by(status=status)
    if po:
        query = query.filter(Style.po == po)
    if q:
        query = query.filter(Style.style_no.ilike(f'%{q}%') | Style.description.ilike(f'%{q}%') | Style.po.ilike(f'%{q}%'))

    all_styles = query.order_by(Style.created_at.desc()).all()
    vids = visible_buyer_ids(current_user)
    bq = Buyer.query.filter_by(is_active=True)
    if vids is not None:
        bq = bq.filter(Buyer.id.in_(vids))
    all_buyers = bq.order_by(Buyer.name).all()
    all_teams = Team.query.all()
    po_list = sorted({r[0] for r in visible_styles_query(Style.query, current_user).filter(Style.po.isnot(None)).filter(Style.po != '').with_entities(Style.po).distinct().all() if r[0]})
    return render_template('styles.html', styles=all_styles, buyers=all_buyers,
                           teams=all_teams, selected_buyer=buyer_id,
                           selected_team=team_id, selected_status=status, search_q=q,
                           po_list=po_list, selected_po=po)


@app.route('/styles/add', methods=['POST'])
@login_required
def add_style():
    style_no = request.form.get('style_no', '').strip()
    po = request.form.get('po', '').strip()
    description = request.form.get('description', '').strip()
    buyer_id = request.form.get('buyer_id', type=int)
    vids = visible_buyer_ids(current_user)
    if vids is not None and buyer_id not in vids:
        flash('You can only add styles for your assigned buyers.', 'danger')
        return redirect(url_for('styles'))
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
    """Parse the active sheet and upsert styles.
    Returns (added, updated, skipped, remarks_added, name_only).
    name_only = [(style_no, po)] for rows skipped only because they have no Buyer
    (re-importable later by Style Name only)."""
    _u = User.query.get(user_id)
    _is_admin = bool(_u and _u.is_admin)
    _vids = visible_buyer_ids(_u) if _u else set()
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
    name_only = []
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
        po = val('po')
        po = str(po).strip() if po is not None else ''
        if not buyer_name:
            # No Buyer: skipped now, but re-importable later by Style Name only
            skipped.append((excel_row, 'Style ' + style_no + ': no Buyer — row skipped.'))
            name_only.append((style_no, po))
            continue
        # Buyer access: non-admins can only import for buyers assigned to them
        _existing = Buyer.query.filter(db.func.lower(Buyer.name) == str(buyer_name).strip().lower()).first()
        if not _is_admin and (_existing is None or _existing.id not in _vids):
            skipped.append((excel_row, 'Style ' + style_no + ': Buyer "' + str(buyer_name).strip() + '" is not assigned to you — row skipped.'))
            continue
        buyer = _existing or _get_or_create_buyer(buyer_name)

        style = Style.query.filter_by(style_no=style_no, buyer_id=buyer.id, po=po).first()
        if style is None:
            # Adopt a Style-Name-only placeholder for this style (no buyer yet)
            style = Style.query.filter_by(style_no=style_no, buyer_id=None, po=po).first()
        if style is None and po:
            # A PO-less copy exists (imported before PO) — adopt it, don't duplicate
            style = Style.query.filter_by(style_no=style_no, buyer_id=buyer.id, po='').first()
        if style is None and po:
            style = Style.query.filter_by(style_no=style_no, buyer_id=None, po='').first()
        if style is None and not po:
            # Blank-PO row: update the most recent copy under this Style No + Buyer
            style = Style.query.filter_by(style_no=style_no, buyer_id=buyer.id).order_by(Style.updated_at.desc()).first()
        is_new = style is None
        if is_new:
            style = Style(style_no=style_no, buyer_id=buyer.id, po=po, created_by=user_id)
            db.session.add(style)
        else:
            style.buyer_id = buyer.id
            if po:
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
    return added, updated, skipped, remarks_added, name_only


def _import_name_only(pairs, user_id):
    """Create Style-Name-only placeholders for (style_no, po) pairs.
    Returns (created, already_there). Skips any pair that already has a style
    with the same Style No + PO (any buyer) — no duplicates."""
    created = 0
    already = 0
    for style_no, po in pairs:
        style_no = str(style_no).strip()
        if not style_no:
            continue
        po = str(po).strip() if po else ''
        existing = Style.query.filter_by(style_no=style_no, po=po).first()
        if existing is not None:
            already += 1
            continue
        db.session.add(Style(style_no=style_no, buyer_id=None, po=po,
                             status='Active', created_by=user_id))
        created += 1
    db.session.commit()
    return created, already


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
            added, updated, skipped, remarks_added, name_only = _import_styles_workbook(wb, current_user.id)
        except Exception as e:
            flash('Could not read this file: ' + str(e), 'danger')
            return redirect(url_for('import_styles'))
        result = {'added': added, 'updated': updated, 'skipped': skipped,
                  'remarks_added': remarks_added, 'name_only': name_only,
                  'filename': f.filename}
        flash('Import finished: ' + str(added) + ' added, ' + str(updated) + ' updated, ' + str(len(skipped)) + ' skipped.', 'success' if not skipped else 'warning')
    return render_template('import_styles.html', result=result)


@app.route('/styles/import/name-only', methods=['POST'])
@login_required
def import_name_only():
    """Second click: import the skipped styles by Style Name only.
    Creates buyer-less placeholders that can be completed manually later."""
    raw = request.form.getlist('pair')
    pairs = []
    for item in raw:
        if '|' in item:
            sn, po = item.split('|', 1)
            pairs.append((sn.strip(), po.strip()))
        elif item.strip():
            pairs.append((item.strip(), ''))
    if not pairs:
        flash('No styles to import.', 'warning')
        return redirect(url_for('import_styles'))
    created, already = _import_name_only(pairs, current_user.id)
    flash(f'Style-Name-only import: {created} created, {already} already existed.', 'success' if created else 'warning')
    return redirect(url_for('styles'))


@app.route('/styles/<int:sid>')
@login_required
def style_detail(sid):
    style = Style.query.get_or_404(sid)
    vids = visible_buyer_ids(current_user)
    if vids is not None and not (
            (style.buyer_id is not None and style.buyer_id in vids) or
            (style.buyer_id is None and style.created_by == current_user.id)):
        flash('You do not have access to this style.', 'danger')
        return redirect(url_for('styles'))
    bq = Buyer.query.filter_by(is_active=True)
    if vids is not None:
        bq = bq.filter(Buyer.id.in_(vids))
    all_buyers = bq.order_by(Buyer.name).all()
    all_teams = Team.query.all()
    return render_template('style_detail.html', style=style, buyers=all_buyers, teams=all_teams)


@app.route('/styles/<int:sid>/edit', methods=['POST'])
@login_required
def edit_style(sid):
    style = Style.query.get_or_404(sid)
    vids = visible_buyer_ids(current_user)
    if vids is not None and not (
            (style.buyer_id is not None and style.buyer_id in vids) or
            (style.buyer_id is None and style.created_by == current_user.id)):
        flash('You do not have access to this style.', 'danger')
        return redirect(url_for('styles'))
    new_buyer = request.form.get('buyer_id', type=int)
    if vids is not None and new_buyer is not None and new_buyer not in vids:
        flash('You can only assign your own buyers.', 'danger')
        return redirect(url_for('style_detail', sid=sid))
    style.style_no = request.form.get('style_no', style.style_no).strip()
    style.po = request.form.get('po', style.po or '').strip()
    style.description = request.form.get('description', '').strip()
    style.buyer_id = new_buyer
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
    vids = visible_buyer_ids(current_user)
    if vids is not None and not (
            (style.buyer_id is not None and style.buyer_id in vids) or
            (style.buyer_id is None and style.created_by == current_user.id)):
        flash('You do not have access to this style.', 'danger')
        return redirect(url_for('styles'))
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
    vids = visible_buyer_ids(current_user)
    bq = Buyer.query.filter_by(is_active=True)
    if vids is not None:
        bq = bq.filter(Buyer.id.in_(vids))
    buyers = bq.order_by(Buyer.name).all()
    teams = Team.query.all()
    po_q = visible_styles_query(Style.query, current_user).filter(Style.po.isnot(None)).filter(Style.po != '')
    po_list = sorted({r[0] for r in po_q.with_entities(Style.po).distinct().all() if r[0]})
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
    return render_template('reports.html', buyers=buyers, teams=teams, report_files=report_files, po_list=po_list)


@app.route('/reports/generate', methods=['POST'])
@login_required
def generate_report():
    report_type = request.form.get('report_type', 'excel')
    buyer_id = request.form.get('buyer_id', type=int)
    team_id = request.form.get('team_id', type=int)
    status = request.form.get('status', '')
    po_filter = request.form.get('po', '').strip()
    style_no_filter = request.form.get('style_no', '').strip()
    include_comments = request.form.get('include_comments') == 'on'

    query = visible_styles_query(Style.query, current_user)
    if buyer_id:
        vids = visible_buyer_ids(current_user)
        if vids is not None and buyer_id not in vids:
            flash('You can only report on your assigned buyers.', 'danger')
            return redirect(url_for('reports'))
        query = query.filter_by(buyer_id=buyer_id)
    if team_id:
        query = query.filter_by(team_id=team_id)
    if status:
        query = query.filter_by(status=status)
    if po_filter:
        query = query.filter(Style.po.ilike(f'%{po_filter}%'))
    if style_no_filter:
        query = query.filter(Style.style_no.ilike(f'%{style_no_filter}%'))
    styles_data = query.order_by(Style.buyer_id, Style.style_no).all()

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    if report_type == 'excel':
        filename = f'SCM_Report_{timestamp}.xlsx'
        filepath = os.path.join(REPORT_DIR, filename)
        _generate_excel(styles_data, filepath, include_comments)
    else:
        filename = f'SCM_Report_{timestamp}.pdf'
        filepath = os.path.join(REPORT_DIR, filename)
        _generate_pdf(styles_data, filepath, include_comments)

    # Auto-download: the file downloads straight away (a copy stays in Reports)
    return send_file(filepath, as_attachment=True, download_name=filename)


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

    navy = "1a3c5e"
    header_fill = PatternFill("solid", fgColor=navy)
    header_font = Font(bold=True, color="FFFFFF", size=11)
    title_font = Font(bold=True, color=navy, size=15)
    sub_font = Font(color="555555", size=10)
    thin = Side(style='thin', color='CCCCCC')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    alt_fill = PatternFill("solid", fgColor="EBF3FB")
    total_fill = PatternFill("solid", fgColor="D9E6F2")
    total_font = Font(bold=True, size=11)
    status_fill = {
        'Completed': PatternFill("solid", fgColor="D5F5E3"),
        'On Hold': PatternFill("solid", fgColor="FDEBD0"),
        'Cancelled': PatternFill("solid", fgColor="FADBD8"),
        'Active': PatternFill("solid", fgColor="D6EAF8"),
    }

    headers = ['#', 'Style No', 'PO', 'Description', 'Buyer', 'Team', 'Season',
               'Category', 'Fabric', 'Color', 'Quantity', 'Unit Price ($)',
               'Total Value ($)', 'Status', 'Created At']
    if include_comments:
        headers.append('Remark (Latest Comment)')
    ncols = len(headers)

    # Title + generated line
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    c = ws.cell(row=1, column=1, value='Supply Chain Management \u2014 Style Report')
    c.font = title_font
    c.alignment = Alignment(horizontal='left', vertical='center')
    ws.row_dimensions[1].height = 26
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols)
    c = ws.cell(row=2, column=1,
               value=f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  Total Styles: {len(styles_data)}")
    c.font = sub_font
    c.alignment = Alignment(horizontal='left', vertical='center')
    ws.row_dimensions[2].height = 18

    # Header row (row 3)
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=3, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = border
    ws.row_dimensions[3].height = 28

    # Data rows from row 4
    for i, style in enumerate(styles_data):
        row_idx = 4 + i
        fill = alt_fill if i % 2 == 1 else PatternFill()
        total_val = (style.quantity or 0) * (style.unit_price or 0)
        latest_comment = ''
        if include_comments and style.comments:
            latest_comment = style.comments[0].comment or ''
        row_data = [
            i + 1, style.style_no, style.po or '', style.description or '',
            style.buyer.name if style.buyer else '',
            style.team.name if style.team else '',
            style.season or '', style.category or '', style.fabric or '',
            style.color or '', style.quantity or 0, style.unit_price or 0,
            round(total_val, 2), style.status,
            style.created_at.strftime('%Y-%m-%d') if style.created_at else ''
        ]
        if include_comments:
            row_data.append(latest_comment)
        for col, val in enumerate(row_data, 1):
            cell = ws.cell(row=row_idx, column=col, value=val)
            cell.fill = fill
            cell.border = border
            cell.alignment = Alignment(vertical='center', wrap_text=True)
            if headers[col - 1] == 'Quantity':
                cell.alignment = Alignment(horizontal='right', vertical='center')
                cell.number_format = '#,##0'
            if headers[col - 1] in ('Unit Price ($)', 'Total Value ($)'):
                cell.alignment = Alignment(horizontal='right', vertical='center')
                cell.number_format = '"$"#,##0.00'
        sc = ws.cell(row=row_idx, column=headers.index('Status') + 1)
        if style.status in status_fill:
            sc.fill = status_fill[style.status]

    # Totals row
    tr = 4 + len(styles_data)
    total_qty = sum(s.quantity or 0 for s in styles_data)
    total_val = sum((s.quantity or 0) * (s.unit_price or 0) for s in styles_data)
    for col in range(1, ncols + 1):
        cell = ws.cell(row=tr, column=col)
        cell.fill = total_fill
        cell.border = border
        cell.font = total_font
    ws.cell(row=tr, column=1, value='TOTAL').alignment = Alignment(horizontal='center', vertical='center')
    qty_col = headers.index('Quantity') + 1
    tot_col = headers.index('Total Value ($)') + 1
    c = ws.cell(row=tr, column=qty_col, value=total_qty)
    c.number_format = '#,##0'
    c.alignment = Alignment(horizontal='right', vertical='center')
    c = ws.cell(row=tr, column=tot_col, value=round(total_val, 2))
    c.number_format = '"$"#,##0.00'
    c.alignment = Alignment(horizontal='right', vertical='center')
    ws.row_dimensions[tr].height = 22

    # Column widths
    widths = {'#': 5, 'Style No': 16, 'PO': 14, 'Description': 28, 'Buyer': 18,
              'Team': 14, 'Season': 10, 'Category': 14, 'Fabric': 14, 'Color': 12,
              'Quantity': 11, 'Unit Price ($)': 13, 'Total Value ($)': 14,
              'Status': 11, 'Created At': 12, 'Remark (Latest Comment)': 45}
    for col, h in enumerate(headers, 1):
        ws.column_dimensions[get_column_letter(col)].width = widths.get(h, 14)

    ws.freeze_panes = 'A4'
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_title_rows = '1:3'

    # Summary sheet (with buyer-wise breakdown)
    ws2 = wb.create_sheet("Summary")
    ws2['A1'] = 'Supply Chain Management - Summary Report'
    ws2['A1'].font = Font(bold=True, size=14, color=navy)
    ws2['A3'] = 'Generated:'
    ws2['B3'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    ws2['A4'] = 'Total Styles:'
    ws2['B4'] = len(styles_data)
    ws2['A5'] = 'Total Quantity:'
    ws2['B5'] = total_qty
    ws2['A6'] = 'Total Value ($):'
    ws2['B6'] = round(total_val, 2)
    for r in range(3, 7):
        ws2.cell(row=r, column=1).font = Font(bold=True)
    # Buyer-wise breakdown
    ws2['A8'] = 'Buyer-wise breakdown'
    ws2['A8'].font = Font(bold=True, size=12, color=navy)
    for j, h in enumerate(['Buyer', 'Styles', 'Quantity', 'Value ($)'], 1):
        cell = ws2.cell(row=9, column=j, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = border
    by_buyer = {}
    for s in styles_data:
        b = s.buyer.name if s.buyer else '(No Buyer)'
        d = by_buyer.setdefault(b, [0, 0, 0.0])
        d[0] += 1
        d[1] += s.quantity or 0
        d[2] += (s.quantity or 0) * (s.unit_price or 0)
    for i, (b, (cnt, qty, val)) in enumerate(sorted(by_buyer.items())):
        r = 10 + i
        ws2.cell(row=r, column=1, value=b).border = border
        ws2.cell(row=r, column=2, value=cnt).border = border
        ws2.cell(row=r, column=3, value=qty).border = border
        c = ws2.cell(row=r, column=4, value=round(val, 2))
        c.border = border
        c.number_format = '"$"#,##0.00'
    ws2.column_dimensions['A'].width = 30
    ws2.column_dimensions['B'].width = 12
    ws2.column_dimensions['C'].width = 14
    ws2.column_dimensions['D'].width = 16

    wb.save(filepath)


def _generate_pdf(styles_data, filepath, include_comments=False):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.enums import TA_LEFT

    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#888888'))
        canvas.drawCentredString(doc.pagesize[0] / 2, 0.9 * cm,
                                 f'Supply Chain Management  |  Page {doc.page}')
        canvas.restoreState()

    doc = SimpleDocTemplate(filepath, pagesize=landscape(A4),
                            leftMargin=1 * cm, rightMargin=1 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.4 * cm)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle('Title2', parent=styles['Title'],
                                 fontSize=16, textColor=colors.HexColor('#1a3c5e'),
                                 spaceAfter=4, alignment=TA_LEFT)
    sub_style = ParagraphStyle('Sub', parent=styles['Normal'],
                               fontSize=9, textColor=colors.HexColor('#555555'),
                               spaceAfter=2)
    total_qty = sum(s.quantity or 0 for s in styles_data)
    total_val = sum((s.quantity or 0) * (s.unit_price or 0) for s in styles_data)
    elements.append(Paragraph('Supply Chain Management \u2014 Style Report', title_style))
    elements.append(Paragraph(
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} &nbsp;|&nbsp; "
        f"<b>Total Styles:</b> {len(styles_data)} &nbsp;|&nbsp; "
        f"<b>Total Qty:</b> {total_qty:,} &nbsp;|&nbsp; "
        f"<b>Total Value:</b> ${total_val:,.2f}", sub_style))
    elements.append(Spacer(1, 0.4 * cm))

    pstyle = ParagraphStyle('Cell', parent=styles['Normal'], fontSize=8, leading=10)
    pstyle_b = ParagraphStyle('CellB', parent=pstyle, fontName='Helvetica-Bold')
    headers = ['#', 'Style No', 'PO', 'Buyer', 'Season', 'Category', 'Qty', 'Price ($)', 'Total ($)', 'Status']
    if include_comments:
        headers.append('Remark')

    table_data = [[Paragraph(f'<b>{h}</b>', ParagraphStyle('H', parent=pstyle, textColor=colors.white)) for h in headers]]
    for idx, style in enumerate(styles_data, 1):
        row = [
            str(idx), style.style_no, style.po or '',
            style.buyer.name if style.buyer else '',
            style.season or '', style.category or '',
            f"{style.quantity or 0:,}", f"{style.unit_price or 0:.2f}",
            f"{(style.quantity or 0) * (style.unit_price or 0):,.2f}",
            style.status
        ]
        if include_comments:
            row.append(style.comments[0].comment if style.comments else '')
        table_data.append([Paragraph(str(v), pstyle) for v in row])
    # Totals row
    tot_row = ['', '', '', '', '', '', f"<b>{total_qty:,}</b>", '', f"<b>${total_val:,.2f}</b>", '']
    if include_comments:
        tot_row.append('')
    table_data.append([Paragraph(v, pstyle_b) if v else Paragraph('', pstyle) for v in tot_row])

    col_widths = [0.9 * cm, 2.8 * cm, 2.4 * cm, 3.4 * cm, 2.2 * cm, 2.6 * cm, 1.6 * cm, 1.8 * cm, 2.0 * cm, 2.2 * cm]
    if include_comments:
        col_widths.append(4.5 * cm)

    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a3c5e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#EBF3FB')]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#D9E6F2')),
        ('LINEABOVE', (0, -1), (-1, -1), 1, colors.HexColor('#1a3c5e')),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]
    table.setStyle(TableStyle(style_cmds))
    elements.append(table)
    doc.build(elements, onFirstPage=_footer, onLaterPages=_footer)

# ─── Init DB & Run ────────────────────────────────────────────────────────────
def init_db():
    with app.app_context():
        db.create_all()
        # Lightweight migrations for existing installs
        try:
            from sqlalchemy import inspect as _sa_inspect, text as _sa_text
            _cols = [c['name'] for c in _sa_inspect(db.engine).get_columns('style')]
            if 'po' not in _cols:
                with db.engine.begin() as _conn:
                    _conn.execute(_sa_text('ALTER TABLE style ADD COLUMN po VARCHAR(100)'))
                    _conn.execute(_sa_text("UPDATE style SET po = '' WHERE po IS NULL"))
            # Team leader column
            _tcols = [c['name'] for c in _sa_inspect(db.engine).get_columns('team')]
            if 'leader_id' not in _tcols:
                with db.engine.begin() as _conn:
                    _conn.execute(_sa_text('ALTER TABLE team ADD COLUMN leader_id INTEGER REFERENCES "user"(id)'))
            # Buyer optional on styles (Style-Name-only placeholders)
            _scols = {c['name']: c for c in _sa_inspect(db.engine).get_columns('style')}
            if _scols.get('buyer_id', {}).get('nullable') is False:
                with db.engine.begin() as _conn:
                    _conn.execute(_sa_text('ALTER TABLE style ALTER COLUMN buyer_id DROP NOT NULL'))
        except Exception as _e:
            print(f"Warning during migration: {_e}")
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
