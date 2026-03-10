"""Authentication routes for orrbit."""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required

from ..activity import log_action
from ..auth import get_user_by_username, check_rate_limit, record_failure

bp = Blueprint('auth', __name__)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        ip = request.remote_addr

        if not check_rate_limit(ip):
            flash('Too many failed attempts. Try again later.', 'error')
            return render_template('login.html'), 429

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember') == 'on'

        user = get_user_by_username(username)
        if user and user.check_password(password):
            login_user(user, remember=remember)
            log_action('login', username, ip=ip)
            next_page = request.args.get('next', '')
            # Prevent open redirect — only allow relative paths
            if not next_page or not next_page.startswith('/') or next_page.startswith('//'):
                next_page = url_for('browse.index')
            return redirect(next_page)

        record_failure(ip)
        flash('Invalid username or password.', 'error')

    return render_template('login.html')


@bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
