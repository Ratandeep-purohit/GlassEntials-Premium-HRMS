import os
import re

# Base directory
base_dir = r"d:\projects\HRMS_Glassentials"

# Files to update
files_to_update = [
    r"payroll\templates\payroll.html",
    r"attendance\templates\createshift.html",
    r"attendance\templates\assignshift.html",
    r"employees\templates\addemployee.html",
    r"employees\templates\department.html",
    r"employees\templates\bulk_import.html",
    r"employees\templates\designation.html",
    r"employees\templates\editemployee.html",
    r"employees\templates\employee.html",
    r"employees\templates\viewemployee.html",
]

# Read home.html
home_html_path = os.path.join(base_dir, r"home\templates\home.html")
with open(home_html_path, "r", encoding="utf-8") as f:
    home_content = f.read()

# Extract header
header_pattern = re.compile(r'(<header class="platform-header">.*?</header>)', re.DOTALL)
match = header_pattern.search(home_content)
if not match:
    print("Could not find header in home.html")
    exit(1)

new_header = match.group(1)
# Remove the active class from dashboard so it doesn't show active everywhere
new_header_generic = new_header.replace('class="nav-pill active"', 'class="nav-pill"')

for file_rel_path in files_to_update:
    file_path = os.path.join(base_dir, file_rel_path)
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        continue
    
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Check if the file has a header
    if header_pattern.search(content):
        
        # Determine if we should set a specific nav-pill to active based on folder
        modified_header = new_header_generic
        if 'employees' in file_rel_path:
            # We want to make the employees nav-pill active
            # The employees nav pill is <a href="#" class="nav-pill">\n<i class="fas fa-users-rectangle">
            modified_header = modified_header.replace(
                '<a href="#" class="nav-pill">\n                    <i class="fas fa-users-rectangle">',
                '<a href="#" class="nav-pill active">\n                    <i class="fas fa-users-rectangle">'
            )
        elif 'attendance' in file_rel_path:
            modified_header = modified_header.replace(
                '<a href="#" class="nav-pill">\n                    <i class="fas fa-fingerprint">',
                '<a href="#" class="nav-pill active">\n                    <i class="fas fa-fingerprint">'
            )
        elif 'payroll' in file_rel_path:
            modified_header = modified_header.replace(
                '<a href="#" class="nav-pill">\n                    <i class="fas fa-receipt">',
                '<a href="#" class="nav-pill active">\n                    <i class="fas fa-receipt">'
            )
        
        # Replace the header
        new_content = header_pattern.sub(modified_header, content)
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"Updated {file_rel_path}")
    else:
        print(f"No header found in {file_rel_path}")

print("Done updating navbars.")
