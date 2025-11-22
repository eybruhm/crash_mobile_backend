# CRASH Backend - Mobile Integration Guide (React Native/Expo)

This guide helps your friend integrate this Django backend with a React Native Expo app.

---

## 1. Project Setup (Mobile Side)

Your friend should have already run:
```bash
npx create-expo-app@latest "YourAppName"
cd YourAppName
npx expo start
```

### Install Required Packages
```bash
# API communication
npm install axios

# State management (optional but recommended)
npm install @reduxjs/toolkit react-redux

# Navigation (if not already installed)
npx expo install @react-navigation/native @react-navigation/stack @react-navigation/bottom-tabs

# Image picker for file uploads
npx expo install expo-image-picker

# Location services
npx expo install expo-location

# Secure storage for tokens
npx expo install expo-secure-store

# For QR code display
npx expo install react-native-qrcode-svg

# For maps
npx expo install react-native-maps
```

---

## 2. Backend Connection Setup

### Configure Base URL

Create `src/config/api.js`:
```javascript
import axios from 'axios';

// Development: Use your local IP (not localhost)
// Find your IP: Windows (ipconfig), Mac/Linux (ifconfig)
const BASE_URL = 'http://192.168.1.XXX:8000'; // Replace with your IP

// Production: Use deployed backend URL
// const BASE_URL = 'https://your-backend.com';

const api = axios.create({
  baseURL: BASE_URL,
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor for adding auth token
api.interceptors.request.use(
  async (config) => {
    const token = await getToken(); // Implement token retrieval
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Handle unauthorized (logout user)
    }
    return Promise.reject(error);
  }
);

export default api;
```

**Important:** 
- Replace `192.168.1.XXX` with your actual local IP
- For Expo tunnel mode: use the Expo provided URL
- For production: use your deployed backend domain

---

## 3. API Service Examples

Create `src/services/` folder with service files:

### `authService.js`
```javascript
import api from '../config/api';
import * as SecureStore from 'expo-secure-store';

export const login = async (email, password) => {
  try {
    const response = await api.post('/login/', { email, password });
    const { token, user, role } = response.data;
    
    // Store token securely
    await SecureStore.setItemAsync('authToken', token);
    await SecureStore.setItemAsync('userRole', role);
    await SecureStore.setItemAsync('userData', JSON.stringify(user));
    
    return { success: true, user, role };
  } catch (error) {
    return { 
      success: false, 
      error: error.response?.data?.detail || 'Login failed' 
    };
  }
};

export const logout = async () => {
  await SecureStore.deleteItemAsync('authToken');
  await SecureStore.deleteItemAsync('userRole');
  await SecureStore.deleteItemAsync('userData');
};

export const getToken = async () => {
  return await SecureStore.getItemAsync('authToken');
};

export const getUserData = async () => {
  const data = await SecureStore.getItemAsync('userData');
  return data ? JSON.parse(data) : null;
};
```

### `reportService.js`
```javascript
import api from '../config/api';

export const createReport = async (reportData) => {
  try {
    const response = await api.post('/reports/', reportData);
    return { success: true, data: response.data };
  } catch (error) {
    return { 
      success: false, 
      error: error.response?.data || 'Failed to create report' 
    };
  }
};

export const getActiveReports = async () => {
  try {
    const response = await api.get('/reports/');
    return { success: true, data: response.data };
  } catch (error) {
    return { success: false, error: 'Failed to fetch reports' };
  }
};

export const getReportById = async (reportId) => {
  try {
    const response = await api.get(`/reports/${reportId}/`);
    return { success: true, data: response.data };
  } catch (error) {
    return { success: false, error: 'Report not found' };
  }
};

export const updateReportStatus = async (reportId, status, remarks) => {
  try {
    const response = await api.patch(`/reports/${reportId}/`, {
      status,
      remarks,
    });
    return { success: true, data: response.data };
  } catch (error) {
    return { success: false, error: 'Failed to update report' };
  }
};

export const getReportRoute = async (reportId) => {
  try {
    const response = await api.get(`/reports/${reportId}/route/`);
    return { success: true, data: response.data };
  } catch (error) {
    return { success: false, error: 'Failed to get route' };
  }
};
```

### `messageService.js`
```javascript
import api from '../config/api';

export const getMessages = async (reportId) => {
  try {
    const response = await api.get(`/reports/${reportId}/messages/`);
    return { success: true, data: response.data };
  } catch (error) {
    return { success: false, error: 'Failed to fetch messages' };
  }
};

export const sendMessage = async (reportId, messageData) => {
  try {
    const response = await api.post(`/reports/${reportId}/messages/`, messageData);
    return { success: true, data: response.data };
  } catch (error) {
    return { success: false, error: 'Failed to send message' };
  }
};
```

### `mediaService.js`
```javascript
import api from '../config/api';

export const uploadMedia = async (reportId, senderId, fileType, fileUri) => {
  try {
    const formData = new FormData();
    formData.append('report', reportId);
    formData.append('sender_id', senderId);
    formData.append('file_type', fileType);
    
    // Extract filename from URI
    const filename = fileUri.split('/').pop();
    const match = /\.(\w+)$/.exec(filename);
    const type = match ? `image/${match[1]}` : 'image/jpeg';
    
    formData.append('uploaded_file', {
      uri: fileUri,
      name: filename,
      type: type,
    });

    const response = await api.post('/media/', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    
    return { success: true, data: response.data };
  } catch (error) {
    console.error('Upload error:', error.response?.data);
    return { 
      success: false, 
      error: error.response?.data?.upload || 'Upload failed' 
    };
  }
};

export const getMediaForReport = async (reportId) => {
  try {
    const response = await api.get(`/media/?report=${reportId}`);
    return { success: true, data: response.data };
  } catch (error) {
    return { success: false, error: 'Failed to fetch media' };
  }
};
```

---

## 4. Usage Examples in Components

### Example: Submit Report with Location
```javascript
import React, { useState, useEffect } from 'react';
import { View, Button, Alert } from 'react-native';
import * as Location from 'expo-location';
import { createReport } from '../services/reportService';
import { getUserData } from '../services/authService';

export default function SubmitReportScreen() {
  const [location, setLocation] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    (async () => {
      let { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== 'granted') {
        Alert.alert('Permission denied', 'Location access is required');
        return;
      }

      let loc = await Location.getCurrentPositionAsync({});
      setLocation(loc.coords);
    })();
  }, []);

  const handleSubmit = async () => {
    setLoading(true);
    const user = await getUserData();
    
    const reportData = {
      category: 'Accident',
      description: 'Car accident on highway',
      latitude: location.latitude.toString(),
      longitude: location.longitude.toString(),
      reporter: user.user_id,
    };

    const result = await createReport(reportData);
    setLoading(false);

    if (result.success) {
      Alert.alert('Success', 'Report submitted successfully');
    } else {
      Alert.alert('Error', result.error);
    }
  };

  return (
    <View>
      <Button 
        title="Submit Report" 
        onPress={handleSubmit} 
        disabled={!location || loading}
      />
    </View>
  );
}
```

### Example: Upload Image
```javascript
import React from 'react';
import { Button, Alert } from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import { uploadMedia } from '../services/mediaService';

export default function UploadImageButton({ reportId, senderId }) {
  const handleImagePick = async () => {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      allowsEditing: true,
      quality: 0.8,
    });

    if (!result.canceled) {
      const uploadResult = await uploadMedia(
        reportId,
        senderId,
        'image',
        result.assets[0].uri
      );

      if (uploadResult.success) {
        Alert.alert('Success', 'Image uploaded');
      } else {
        Alert.alert('Error', uploadResult.error);
      }
    }
  };

  return <Button title="Upload Image" onPress={handleImagePick} />;
}
```

### Example: Display Messages (Chat)
```javascript
import React, { useState, useEffect } from 'react';
import { FlatList, Text, TextInput, Button, View } from 'react-native';
import { getMessages, sendMessage } from '../services/messageService';

export default function ChatScreen({ reportId, userId, userType }) {
  const [messages, setMessages] = useState([]);
  const [inputText, setInputText] = useState('');

  useEffect(() => {
    fetchMessages();
    const interval = setInterval(fetchMessages, 5000); // Poll every 5s
    return () => clearInterval(interval);
  }, []);

  const fetchMessages = async () => {
    const result = await getMessages(reportId);
    if (result.success) {
      setMessages(result.data);
    }
  };

  const handleSend = async () => {
    if (!inputText.trim()) return;

    const messageData = {
      sender_id: userId,
      sender_type: userType, // 'user' or 'police'
      receiver_id: 'receiver-uuid', // Determine based on context
      message_content: inputText,
    };

    const result = await sendMessage(reportId, messageData);
    if (result.success) {
      setInputText('');
      fetchMessages();
    }
  };

  return (
    <View style={{ flex: 1 }}>
      <FlatList
        data={messages}
        keyExtractor={(item) => item.message_id}
        renderItem={({ item }) => (
          <Text>{item.sender_type}: {item.message_content}</Text>
        )}
      />
      <TextInput
        value={inputText}
        onChangeText={setInputText}
        placeholder="Type message..."
      />
      <Button title="Send" onPress={handleSend} />
    </View>
  );
}
```

---

## 5. Testing Backend Connection

### Quick Test Component
```javascript
import React, { useEffect, useState } from 'react';
import { View, Text } from 'react-native';
import api from '../config/api';

export default function TestConnection() {
  const [status, setStatus] = useState('Testing...');

  useEffect(() => {
    api.get('/reports/')
      .then(() => setStatus('✅ Connected to backend'))
      .catch(() => setStatus('❌ Cannot connect to backend'));
  }, []);

  return (
    <View>
      <Text>{status}</Text>
    </View>
  );
}
```

---

## 6. Common Issues & Solutions

### Issue: Network request failed
**Cause:** Wrong IP address or backend not running  
**Solution:**
- Ensure Django server is running: `python manage.py runserver 0.0.0.0:8000`
- Use your machine's local IP, not `localhost` or `127.0.0.1`
- Check firewall allows port 8000
- Try tunnel mode: `npx expo start --tunnel`

### Issue: CORS errors (web only)
**Solution:** Install django-cors-headers on backend (already documented in API_ENDPOINTS.md)

### Issue: File upload fails
**Cause:** Incorrect multipart/form-data format  
**Solution:** Use FormData as shown in `mediaService.js`

### Issue: 401 Unauthorized
**Cause:** Missing or invalid token  
**Solution:** Check token is being sent in Authorization header

---

## 7. Environment Variables (Mobile)

Create `.env` in root of Expo project:
```
API_URL=http://192.168.1.XXX:8000
GOOGLE_MAPS_API_KEY=your-key-here
```

Install dotenv:
```bash
npm install react-native-dotenv
```

Configure `babel.config.js`:
```javascript
module.exports = function(api) {
  api.cache(true);
  return {
    presets: ['babel-preset-expo'],
    plugins: [
      ['module:react-native-dotenv', {
        moduleName: '@env',
        path: '.env',
      }]
    ]
  };
};
```

Use in code:
```javascript
import { API_URL } from '@env';
```

---

## 8. Production Deployment

When deploying backend to production:

1. **Update API Base URL**
```javascript
const BASE_URL = 'https://your-backend-domain.com';
```

2. **Enable HTTPS** (required for Expo apps)

3. **Update Django Settings**
```python
ALLOWED_HOSTS = ['your-backend-domain.com']
DEBUG = False
CORS_ALLOWED_ORIGINS = ['https://your-frontend-domain.com']
```

4. **Use environment variables** for both frontend and backend configurations

---

## 9. Recommended Project Structure

```
YourExpoApp/
├── src/
│   ├── config/
│   │   └── api.js              # Axios configuration
│   ├── services/
│   │   ├── authService.js      # Authentication
│   │   ├── reportService.js    # Reports
│   │   ├── messageService.js   # Chat
│   │   └── mediaService.js     # File uploads
│   ├── screens/
│   │   ├── LoginScreen.js
│   │   ├── ReportListScreen.js
│   │   ├── CreateReportScreen.js
│   │   └── ChatScreen.js
│   ├── components/
│   │   └── ...
│   └── navigation/
│       └── AppNavigator.js
├── App.js
└── package.json
```

---

## 10. Next Steps for Your Friend

1. ✅ Install required npm packages
2. ✅ Create `api.js` configuration with your backend IP
3. ✅ Create service files (`authService.js`, `reportService.js`, etc.)
4. ✅ Test connection with simple GET request
5. ✅ Implement login screen
6. ✅ Build report submission flow
7. ✅ Add image upload functionality
8. ✅ Implement real-time chat

---

## Resources

- [Expo Documentation](https://docs.expo.dev/)
- [React Native Maps](https://docs.expo.dev/versions/latest/sdk/map-view/)
- [Expo Image Picker](https://docs.expo.dev/versions/latest/sdk/imagepicker/)
- [Axios Documentation](https://axios-http.com/docs/intro)
- [React Navigation](https://reactnavigation.org/)

For questions, refer to `API_ENDPOINTS.md` for backend endpoint details.
