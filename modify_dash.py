import re

with open(r'e:\projects\HRMS_Glassentials\leaves\templates\leaves\leave_dashboard.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Update Hero HTML
hero_html_old = """    <div class="hero-banner">
        <div class="hero-text">
            <h1>Leave Dashboard</h1>
            <p>Manage your time off and track team availability.</p>
        </div>
        <div class="header-actions" style="display: flex; gap: 12px;">
            <a href="{% url 'leaves:rh_picker' %}" class="punch-btn" style="background: rgba(124, 58, 237, 0.1); color: #7c3aed; border: 1px solid #7c3aed; text-decoration: none;">
                <i class="fas fa-gift"></i> Claim Restricted Holiday
            </a>
            <button class="punch-btn" style="background: rgba(37, 99, 235, 0.1); color: var(--accent); border: 1px solid var(--accent);" onclick="openCompOffModal()">
                <i class="fas fa-history"></i> Request Comp-off Credit
            </button>
            <a href="{% url 'leaves:apply_leave' %}" class="punch-btn" style="text-decoration: none;">
                <i class="fas fa-plus"></i> Apply for Leave
            </a>
        </div>

    </div>"""

hero_html_new = """    <div class="dashboard-hero">
        <div class="dashboard-hero-left">
            <div class="dashboard-hero-eyebrow">
                <i class="fas fa-calendar-alt"></i> Leave Module
            </div>
            <h1 class="dashboard-hero-title">Leave Dashboard</h1>
            <p class="dashboard-hero-subtitle">Manage your time off and track team availability.</p>
        </div>
        <div class="dashboard-hero-actions" style="display: flex; gap: 12px; z-index:1; flex-wrap:wrap; justify-content: flex-end;">
            <a href="{% url 'leaves:rh_picker' %}" class="dash-hero-btn dash-hero-btn-outline">
                <i class="fas fa-gift"></i> Claim RH
            </a>
            <button class="dash-hero-btn dash-hero-btn-outline" onclick="openCompOffModal()">
                <i class="fas fa-history"></i> Request Comp-off
            </button>
            <a href="{% url 'leaves:apply_leave' %}" class="dash-hero-btn dash-hero-btn-solid">
                <i class="fas fa-plus"></i> Apply for Leave
            </a>
        </div>
    </div>"""

html = html.replace(hero_html_old, hero_html_new)

# 2. Add New CSS
css_new = """    }

    /* ═══ Professional Dashboard Hero ═══ */
    .dashboard-hero {
        background: linear-gradient(135deg, #1e40af 0%, #2563eb 50%, #3b82f6 100%);
        border-radius: 22px;
        padding: 32px 36px;
        margin-bottom: 32px;
        position: relative;
        overflow: hidden;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 20px;
    }
    .dashboard-hero::before {
        content: '';
        position: absolute;
        top: -60px; right: -60px;
        width: 220px; height: 220px;
        border-radius: 50%;
        background: rgba(255,255,255,0.07);
    }
    .dashboard-hero::after {
        content: '';
        position: absolute;
        bottom: -40px; left: 30%;
        width: 160px; height: 160px;
        border-radius: 50%;
        background: rgba(255,255,255,0.05);
    }
    .dashboard-hero-left { position: relative; z-index: 1; }
    .dashboard-hero-eyebrow {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        background: rgba(255,255,255,0.15);
        border: 1px solid rgba(255,255,255,0.2);
        border-radius: 999px;
        padding: 5px 14px;
        font-size: 11px;
        font-weight: 800;
        color: rgba(255,255,255,0.9);
        letter-spacing: 0.8px;
        text-transform: uppercase;
        margin-bottom: 14px;
    }
    .dashboard-hero-title {
        margin: 0 0 6px;
        font-size: 28px;
        font-weight: 900;
        color: #fff;
        letter-spacing: -0.5px;
    }
    .dashboard-hero-subtitle {
        margin: 0;
        font-size: 13px;
        color: rgba(255,255,255,0.7);
        font-weight: 600;
    }
    .dash-hero-btn {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 10px 18px;
        border-radius: 12px;
        font-size: 13px;
        font-weight: 700;
        text-decoration: none;
        transition: all 0.2s;
        cursor: pointer;
    }
    .dash-hero-btn-outline {
        background: rgba(255,255,255,0.15);
        border: 1px solid rgba(255,255,255,0.25);
        color: #fff;
        backdrop-filter: blur(10px);
    }
    .dash-hero-btn-outline:hover {
        background: rgba(255,255,255,0.25);
        transform: translateY(-1px);
    }
    .dash-hero-btn-solid {
        background: #fff;
        color: #1e40af;
        border: none;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }
    .dash-hero-btn-solid:hover {
        background: #f8fafc;
        transform: translateY(-1px);
        box-shadow: 0 6px 16px rgba(0,0,0,0.15);
    }
    
    /* Premium Cells */
    .bal-cell {
        border-radius: 14px;
        padding: 16px;
        text-align: center;
        position: relative;
        overflow: hidden;
    }
    .bal-cell.avail { background: linear-gradient(135deg, rgba(37,99,235,.06), rgba(37,99,235,.12)); border: 1px solid rgba(37,99,235,.15); }
    .bal-cell.used { background: #f8fafc; border: 1px solid var(--border-light); }
    .bal-cell.pending { background: linear-gradient(135deg, rgba(245,158,11,.05), rgba(245,158,11,.1)); border: 1px solid rgba(245,158,11,.2); }
    .bal-cell-lbl { font-size: 9px; font-weight: 900; text-transform: uppercase; letter-spacing: .6px; color: var(--text-secondary); }
    .bal-cell-val { font-size: 24px; font-weight: 900; margin-top: 4px; line-height: 1; }
    .bal-cell.avail .bal-cell-val { color: var(--accent); }
    .bal-cell.used .bal-cell-val { color: var(--text-main); }
    .bal-cell.pending .bal-cell-val { color: #f59e0b; }
    
    @media (max-width: 768px) {
        .dashboard-hero { flex-direction: column; align-items: flex-start; padding: 24px; }
        .dashboard-hero-actions { width: 100%; justify-content: flex-start; }
        .dash-hero-btn { flex: 1; justify-content: center; }
    }
</style>"""

html = html.replace("    }\n</style>", css_new)

# 3. Update Policy Balance Rows HTML
policy_row_old = """                <div class="policy-balance-row">
                    <div class="policy-balance-cell">
                        <div class="policy-balance-label">Available</div>
                        <div class="policy-balance-value">{{ card.available }}</div>
                    </div>
                    <div class="policy-balance-cell">
                        <div class="policy-balance-label">Used</div>
                        <div class="policy-balance-value">{{ card.balance.used_balance }}</div>
                    </div>
                    <div class="policy-balance-cell">
                        <div class="policy-balance-label">Pending</div>
                        <div class="policy-balance-value">{{ card.balance.pending_balance }}</div>
                    </div>
                </div>"""

policy_row_new = """                <div class="policy-balance-row">
                    <div class="bal-cell avail" style="padding: 12px;">
                        <div class="bal-cell-lbl">Available</div>
                        <div class="bal-cell-val">{{ card.available }}</div>
                    </div>
                    <div class="bal-cell used" style="padding: 12px;">
                        <div class="bal-cell-lbl">Used</div>
                        <div class="bal-cell-val">{{ card.balance.used_balance }}</div>
                    </div>
                    <div class="bal-cell pending" style="padding: 12px;">
                        <div class="bal-cell-lbl">Pending</div>
                        <div class="bal-cell-val">{{ card.balance.pending_balance }}</div>
                    </div>
                </div>"""

html = html.replace(policy_row_old, policy_row_new)

with open(r'e:\projects\HRMS_Glassentials\leaves\templates\leaves\leave_dashboard.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("HTML modified successfully.")
