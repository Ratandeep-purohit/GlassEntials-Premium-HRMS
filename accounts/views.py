from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import get_user_model
from django.contrib import messages

user=get_user_model()

def landing_page(request):
    return render(request,'landing_page.html')

def login_view(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user_auth = authenticate(request, username=username, password=password)
        if user_auth is not None:
            login(request, user_auth)
            messages.success(request, f"Welcome back, {user_auth.username}!")
            return redirect('home')
        else:
            messages.error(request, "Invalid username or password.")
            return redirect('login')
    return render(request, 'login.html')

def register_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        org_choice = request.POST.get('organization')
        org_name = request.POST.get('org_name')
        org_code = request.POST.get('org_code')
        password = request.POST.get('password')
        
        if user.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
            return redirect('register')
        if user.objects.filter(email=email).exists():
            messages.error(request, "Email already exists.")
            return redirect('register')
            
        org_instance = None
        from .models import Organization
        import uuid
        
        if org_choice == 'org1':
            if not org_name:
                messages.error(request, "Organization name is required.")
                return redirect('register')
            unique_code = f"{org_name[:4].upper()}-{str(uuid.uuid4())[:6].upper()}"
            org_instance = Organization.objects.create(name=org_name, unique_code=unique_code)
        elif org_choice == 'org2':
            if not org_code:
                messages.error(request, "Organization unique code is required.")
                return redirect('register')
            try:
                org_instance = Organization.objects.get(unique_code=org_code)
            except Organization.DoesNotExist:
                messages.error(request, "Invalid organization code.")
                return redirect('register')
        else:
            messages.error(request, "Please select an organization setup.")
            return redirect('register')

        # Create user
        new_user = user.objects.create_user(username=username, email=email, password=password, phone=phone)
        new_user.organization = org_instance
        new_user.save()
        
        messages.success(request, "Account created successfully! Please login.")
        return redirect('login')
        
    return render(request, 'register.html')

def error_404(request, exception):
    return render(request, '404.html', status=404)

def error_500(request):
    return render(request, '500.html', status=500)